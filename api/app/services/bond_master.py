"""Bond master (bond_master) from several sources merged by ISIN.

Sources (pure parsers; malformed rows are counted in `skipped`, never raised). Tags in brackets
are stored in bond_master.sources:
  [seed_sgb]      api/data/sgb_tranches.csv    authoritative SGB tranches (optional)
  [seed_tax_free] api/data/tax_free_bonds.csv  tax-free / 54EC bonds (optional)
  [debt]          NSE DEBT.csv                 base list (15 columns; the ISIN column has no header)
  [nse_ratings]   NSE liveBonds-traded-on-cm   credit rating + agency (optional, enrichment only)
  [nse_sgb]       NSE sovereign-gold-bonds     issue price, joined by NSE symbol (optional)
  [bhav]          NSE UDiFF CM bhavcopy zip    GB -> sovereign gold bond (optional)

Merge priority per field: seeds > debt > nse_ratings/nse_sgb > bhav; a lower source only fills
fields that are still empty. Rating fields only ever come from nse_ratings. Social Stock Exchange
instruments are left out entirely.
"""

import csv
import io
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.models.bond_master import BondMaster
from app.services import market_files as market
from app.services.market_files import SourceRows, Sources

GOVERNMENT_ISSUER = "Government of India"
BHAV_SERIES = ("GB",)
COLUMNS = [
    "isin", "name", "issuer", "nse_symbol", "nse_series", "face_value", "coupon_rate",
    "maturity_date", "bond_type", "issue_date", "issue_price", "rating", "rating_agency",
    "rating_as_of", "sources",
]  # fmt: skip
SOURCES = ["seed_sgb", "seed_tax_free", "debt", "nse_ratings", "nse_sgb", "bhav"]  # fill order; lower index wins
SEED_TAGS = {"seed_sgb", "seed_tax_free"}
# Fed by optional sources: a NULL in today's row keeps the stored value instead of clearing it.
KEEP_COLUMNS = (
    "issue_date", "issue_price", "rating", "rating_agency", "rating_as_of",
    "face_value", "coupon_rate", "maturity_date",  # nse_ratings/seeds fill gaps in the debt row
)  # fmt: skip
UNKNOWN_BOND_MESSAGE = "Select a bond from the list"
_MONTH_NAMES = [m.capitalize() for m in market.MONTHS]
_TAX_FREE_TEXT = re.compile(r"TAX[\s-]?FREE|\bTF\b")
_TAX_FREE_SYMBOL = re.compile(r"TF$")
_COUPON_IN_NAME = re.compile(r"^(\d+(?:\.\d+)?)%")
_STATE_SUFFIX = re.compile(r"\s*(?:-\s*Union Territory|State)\s*$", re.IGNORECASE)
_STATE_FIXES = {
    "Chattisgarh": "Chhattisgarh",
    "Orissa": "Odisha",
    "Tamilnadu": "Tamil Nadu",
    "Uttaranchal": "Uttarakhand",
}


@dataclass(frozen=True)
class BondImportResult:
    sources: dict[str, int]  # parsed rows per source
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    skipped: int
    last_seen_refreshed: int = 0
    excluded: int = 0
    with_rating: int = 0
    bhav_date: date | None = None
    bhav_error: str | None = None
    errors: dict[str, str] = field(default_factory=dict)  # optional sources that failed or were missing


def _row(**values) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(values)
    return row


def is_social_exchange(symbol: str | None, series: str | None) -> bool:
    """Social Stock Exchange instruments: series SE, or NSE symbols ending in -SE (listed under N0)."""
    return market.s(series).upper() == "SE" or market.s(symbol).upper().endswith("-SE")


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(market.s(value))
    except ValueError:
        return market.parse_date(value)


def _price(value) -> Decimal | None:
    return market.decimal_value(None if value is None else str(value), "0.01", 10**12)


def _coupon(value: str | None) -> Decimal | None:
    return market.decimal_value(value, "0.001", 1000)


def derive_bond_type(series: str | None, symbol: str | None, name: str | None, issuer: str | None) -> str:
    """NSE debt series/name -> app bond type."""
    series = market.s(series).upper()
    if series in ("GS", "TB", "SG"):
        return "government"
    if series == "GB":
        return "sgb"
    text = f"{market.s(name)} {market.s(issuer)}".upper()
    if _TAX_FREE_TEXT.search(text) or _TAX_FREE_SYMBOL.search(market.s(symbol).upper()):
        return "tax_free"
    return "corporate"


# --- Parsers -------------------------------------------------------------------


def _bond_name(issuer: str, coupon: Decimal | None, maturity: date | None, symbol: str) -> str:
    parts = [issuer]
    if coupon:
        parts.append(f"{coupon.normalize():f}%")
    if maturity:
        parts.append(f"{maturity.day:02d} {_MONTH_NAMES[maturity.month - 1]} {maturity.year}")
    return f"{' '.join(parts)} ({symbol})"[:300]


def _state_name(issuer: str) -> str:
    state = _STATE_SUFFIX.sub("", issuer).strip()
    return _STATE_FIXES.get(state, state)


def bond_display_name(
    series: str, issuer: str, coupon: Decimal | None, maturity: date | None, symbol: str
) -> str:
    """Readable names for government paper; corporate bonds keep the 'Issuer coupon date (symbol)' form."""
    series = series.upper()
    rate = f"{coupon.normalize():f}% " if coupon else ""
    if maturity and series == "GS":
        return f"{rate}GOI {maturity.year}"
    if maturity and series == "TB":
        return f"T-Bill {maturity.day:02d} {_MONTH_NAMES[maturity.month - 1]} {maturity.year}"
    if maturity and series == "SG":
        return f"{rate}{_state_name(issuer)} SDL {maturity.year}"[:300]
    return _bond_name(issuer, coupon, maturity, symbol)


def parse_debt(data: bytes | str) -> SourceRows:
    """NSE DEBT.csv; positional because the 15th column (ISIN) has no header."""
    result = SourceRows()
    reader = csv.reader(io.StringIO(market.text(data)))
    next(reader, None)
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        if len(values) < 15:
            result.skipped += 1
            continue
        symbol, issuer, series = market.s(values[0]), market.s(values[1]), market.s(values[2])
        isin = market.s(values[14])
        if is_social_exchange(symbol, series):
            result.excluded += 1
            continue
        if not market.ISIN_RE.match(isin) or not symbol or not issuer:
            result.skipped += 1
            continue
        coupon = _coupon(values[6])
        maturity = market.parse_date(values[9])
        name = bond_display_name(series, issuer, coupon, maturity, symbol)
        result.rows.append(
            _row(
                isin=isin, name=name, issuer=issuer[:300], nse_symbol=symbol[:50],
                nse_series=series[:10] or None, face_value=market.face_value(values[3]),
                coupon_rate=coupon, maturity_date=maturity,
                bond_type=derive_bond_type(series, symbol, name, issuer),
            )  # fmt: skip
        )
    return result


def parse_nse_bhav(data: bytes | str) -> SourceRows:
    """NSE UDiFF CM bhavcopy CSV text: keep gold bonds (GB); other series are ignored."""
    result = SourceRows()
    for rec in market.records(data):
        series = market.s(rec.get("SctySrs")).upper()
        if series not in BHAV_SERIES:
            continue
        isin, symbol, name = market.s(rec.get("ISIN")), market.s(rec.get("TckrSymb")), market.s(rec.get("FinInstrmNm"))
        if not market.ISIN_RE.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        match = _COUPON_IN_NAME.match(name)
        result.rows.append(
            _row(
                isin=isin, name=name[:300], issuer=GOVERNMENT_ISSUER, nse_symbol=symbol[:50],
                nse_series=series, bond_type="sgb", coupon_rate=_coupon(match.group(1)) if match else None,
            )  # fmt: skip
        )
    return result


def parse_seed_sgb(data: bytes | str) -> SourceRows:
    """api/data/sgb_tranches.csv: authoritative SGB tranches. Empty cells are unknown (None)."""
    result = SourceRows()
    for rec in market.records(data):
        isin, name = market.s(rec.get("isin")), market.s(rec.get("series_name"))
        if not market.ISIN_RE.match(isin) or not name:
            result.skipped += 1
            continue
        symbol = market.opt(rec.get("nse_symbol"), 50)
        result.rows.append(
            _row(
                isin=isin, name=name[:300], issuer=GOVERNMENT_ISSUER, nse_symbol=symbol,
                nse_series="GB" if symbol else None, bond_type="sgb",
                issue_date=_iso_date(rec.get("issue_date")), maturity_date=_iso_date(rec.get("maturity_date")),
                coupon_rate=_coupon(rec.get("coupon_rate")), issue_price=_price(rec.get("issue_price")),
            )  # fmt: skip
        )
    return result


def tax_free_display_name(issuer: str, coupon: Decimal | None, maturity: date | None) -> str:
    """'REC Limited 7.38% Tax-free Dec 2027'; without a coupon 'REC Limited Tax-free bond 2027'."""
    if coupon and maturity:
        text = f"{issuer} {coupon.normalize():f}% Tax-free {_MONTH_NAMES[maturity.month - 1]} {maturity.year}"
    elif coupon:
        text = f"{issuer} {coupon.normalize():f}% Tax-free bond"
    else:
        text = f"{issuer} Tax-free bond" + (f" {maturity.year}" if maturity else "")
    return text[:300]


def parse_seed_tax_free(data: bytes | str) -> SourceRows:
    """api/data/tax_free_bonds.csv: kind tax_free -> tax_free (short generated name; the CSV name is the
    long NSDL legal name), 54ec -> other (54EC stays in the name)."""
    result = SourceRows()
    for rec in market.records(data):
        isin, kind = market.s(rec.get("isin")), market.s(rec.get("kind")).lower()
        issuer = market.s(rec.get("issuer"))
        name = market.s(rec.get("name")) or issuer
        if not market.ISIN_RE.match(isin) or not name or kind not in ("tax_free", "54ec"):
            result.skipped += 1
            continue
        coupon, maturity = _coupon(rec.get("coupon_rate")), _iso_date(rec.get("maturity_date"))
        if kind == "54ec" and "54EC" not in name.upper():
            name = f"{name} 54EC"
        if kind == "tax_free":
            name = tax_free_display_name(issuer or name, coupon, maturity)
        result.rows.append(
            _row(
                isin=isin, name=name[:300], issuer=issuer[:300] or None,
                bond_type="tax_free" if kind == "tax_free" else "other",
                coupon_rate=coupon, maturity_date=maturity,
            )  # fmt: skip
        )
    return result


def _json_records(data: bytes | str) -> list[dict]:
    payload = json.loads(market.text(data))
    records = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("JSON has no data list")
    return [r for r in records if isinstance(r, dict)]


def parse_nse_sgb(data: bytes | str) -> SourceRows:
    """NSE sovereign-gold-bonds JSON: no ISIN, so rows carry only nse_symbol + issue_price (joined later)."""
    result = SourceRows()
    for rec in _json_records(data):
        symbol = market.s(rec.get("symbol"))
        price = _price(rec.get("issue_price"))
        if not symbol or price is None or market.s(rec.get("series")).upper() not in ("", "GB"):
            result.skipped += 1
            continue
        result.rows.append(_row(nse_symbol=symbol[:50], issue_price=price))
    return result


def parse_nse_ratings(data: bytes | str, as_of: date) -> SourceRows:
    """NSE liveBonds-traded-on-cm JSON: credit rating and agency per ISIN (rating_as_of = as_of)."""
    result = SourceRows()
    for rec in _json_records(data):
        isin, symbol, series = market.s(rec.get("isin")), market.s(rec.get("symbol")), market.s(rec.get("series"))
        if is_social_exchange(symbol, series):
            result.excluded += 1
            continue
        if not market.ISIN_RE.match(isin):
            result.skipped += 1
            continue
        rating = market.opt(rec.get("credit_rating"), 100)
        result.rows.append(
            _row(
                isin=isin, nse_symbol=symbol[:50] or None, nse_series=series[:10] or None,
                face_value=market.face_value(rec.get("face_value")), coupon_rate=_coupon(rec.get("coupr")),
                maturity_date=market.parse_date(rec.get("maturity_date")),
                rating=rating, rating_agency=market.opt(rec.get("rating_agency"), 100) if rating else None,
                rating_as_of=as_of if rating else None,
            )  # fmt: skip
        )
    return result


# --- Merge / build -------------------------------------------------------------


def merge_rows(by_source: dict[str, list[dict]], seen: dict[str, date], today: date | None = None) -> list[dict]:
    """Merge by ISIN (SOURCES order), tag each row with the sources it was seen in. Seed-only rows
    that have already matured are inactive."""
    rows = market.merge_by_isin(by_source, seen, SOURCES, COLUMNS, ())
    tags: dict[str, set[str]] = defaultdict(set)
    for source, source_rows in by_source.items():
        for row in source_rows:
            tags[row["isin"]].add(source)
    for row in rows:
        row["sources"] = sorted(tags[row["isin"]])
        if today and set(row["sources"]) <= SEED_TAGS and row["maturity_date"] and row["maturity_date"] < today:
            row["is_active"] = False
    return rows


def _optional(
    tag: str, payload, parser, today: date, errors: dict, parsed: dict, seen: dict
) -> None:
    """Optional source whose date is today. A missing file is recorded in `errors` unless already explained."""
    if payload is None:
        errors.setdefault(tag, "not provided")
        return
    market.parse_optional(tag, (today, payload), parser, errors, {}, parsed, seen)


def build_rows(sources: Sources, today: date) -> tuple[list[dict], dict[str, int], int, dict]:
    """Parse and merge. Returns (rows, parsed counts per source, skipped, errors/dates/excluded).

    extra["errors"] holds the bhav error (kept for the existing result shape); extra["source_errors"]
    the other optional sources (nse_sgb, nse_ratings, seed_sgb, seed_tax_free) that failed or were missing.
    """
    parsed: dict[str, SourceRows] = {"debt": parse_debt(sources.debt)}
    seen = {"debt": today}
    errors: dict[str, str | None] = {"bhav": sources.bhav_error}
    dates: dict[str, date | None] = {"bhav": None}
    source_errors: dict[str, str] = dict(sources.extra_errors)
    market.parse_optional(
        "bhav", sources.bhav, lambda d: parse_nse_bhav(market.unzip_first(d)), errors, dates, parsed, seen
    )
    if not parsed["debt"].rows:
        raise ValueError("debt file contained no usable rows")
    _optional("seed_sgb", sources.seed_sgb, parse_seed_sgb, today, source_errors, parsed, seen)
    _optional("seed_tax_free", sources.seed_tax_free, parse_seed_tax_free, today, source_errors, parsed, seen)

    # nse_ratings and nse_sgb only enrich ISINs another source already provides.
    base = [row for result in parsed.values() for row in result.rows]
    base_isins = {r["isin"] for r in base}
    symbol_to_isin = {r["nse_symbol"]: r["isin"] for r in base if r["nse_symbol"]}
    _optional(
        "nse_ratings", sources.nse_ratings, lambda d: parse_nse_ratings(d, today), today, source_errors, parsed, seen
    )
    if "nse_ratings" in parsed:
        parsed["nse_ratings"].rows = [r for r in parsed["nse_ratings"].rows if r["isin"] in base_isins]
    _optional("nse_sgb", sources.nse_sgb, parse_nse_sgb, today, source_errors, parsed, seen)
    if "nse_sgb" in parsed:
        joined = []
        for row in parsed["nse_sgb"].rows:
            isin = symbol_to_isin.get(row["nse_symbol"])
            if isin:
                joined.append(_row(isin=isin, issue_price=row["issue_price"]))
        parsed["nse_sgb"].rows = joined

    rows = merge_rows({k: v.rows for k, v in parsed.items()}, seen, today)
    counts = {k: len(v.rows) for k, v in parsed.items()}
    skipped = sum(v.skipped for v in parsed.values())
    excluded = sum(v.excluded for v in parsed.values())
    return rows, counts, skipped, {
        "errors": errors, "dates": dates, "source_errors": source_errors, "excluded": excluded,
        "missing_sources": missing_sources(parsed),
    }


def missing_sources(parsed: dict) -> list[str]:
    """Tags of sources that did not parse this run (failed, skipped or absent): their stored tags are kept."""
    return [tag for tag in SOURCES if tag not in parsed]


def is_grace_row(nse_symbol: str | None, nse_series: str | None) -> bool:
    return market.is_grace_row(nse_symbol, nse_series, BHAV_SERIES)


def import_bonds(session: Session, sources: Sources, today: date) -> BondImportResult:
    """Upsert every merged row; unseen rows become inactive (SGBs after a grace period). Never deletes."""
    rows, counts, skipped, extra = build_rows(sources, today)
    stats = market.upsert_master(
        session, BondMaster, rows, COLUMNS + ["last_seen", "is_active"], BHAV_SERIES, today, KEEP_COLUMNS,
        extra["missing_sources"],
    )
    return BondImportResult(
        sources=counts,
        total=len(rows),
        inserted=stats.inserted,
        updated=stats.updated,
        unchanged=len(rows) - stats.inserted - stats.updated,
        deactivated=stats.deactivated,
        skipped=skipped,
        last_seen_refreshed=stats.last_seen_refreshed,
        excluded=extra["excluded"],
        with_rating=sum(1 for r in rows if r["rating"]),
        bhav_date=extra["dates"]["bhav"],
        bhav_error=extra["errors"]["bhav"],
        errors=extra["source_errors"],
    )


# --- Lookup / search -----------------------------------------------------------


def get_bond_master(session: Session, master_id: int) -> BondMaster | None:
    if not 1 <= master_id <= 2**31 - 1:
        return None
    return session.get(BondMaster, master_id)


def require_bond_master(session: Session, master_id: int) -> BondMaster:
    """Used by bond create/update: unknown id -> 422 on `master_id`."""
    bond = get_bond_master(session, master_id)
    if bond is None:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "master_id"), "msg": UNKNOWN_BOND_MESSAGE, "input": master_id}]
        )
    return bond


def search_bonds(session: Session, q: str, limit: int = 20) -> list[BondMaster]:
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = sa.select(BondMaster).where(BondMaster.is_active)
    for token in q.split():
        statement = statement.where(
            sa.or_(
                BondMaster.name.icontains(token, autoescape=True),
                BondMaster.nse_symbol.icontains(token, autoescape=True),
                BondMaster.isin.icontains(token, autoescape=True),
                BondMaster.issuer.icontains(token, autoescape=True),
            )
        )
    statement = statement.order_by(
        sa.func.similarity(sa.func.lower(BondMaster.name), q.strip().lower()).desc(),
        BondMaster.name,
        BondMaster.id,
    ).limit(limit)
    return list(session.scalars(statement))
