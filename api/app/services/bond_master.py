"""Bond master (bond_master) from NSE files.

Sources (pure parsers; malformed rows are counted in `skipped`, never raised):
  debt    NSE DEBT.csv                (15 columns; the ISIN column has no header)
  bhav    NSE UDiFF CM bhavcopy zip   GB -> sovereign gold bond; optional

Rows are merged by ISIN: debt wins, bhav only fills fields that are still empty.
"""

import csv
import io
import re
from dataclasses import dataclass
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
    "maturity_date", "bond_type",
]  # fmt: skip
SOURCES = ["debt", "bhav"]  # fill order; lower index wins
UNKNOWN_BOND_MESSAGE = "Select a bond from the list"
_MONTH_NAMES = [m.capitalize() for m in market.MONTHS]
_TAX_FREE_TEXT = re.compile(r"TAX[\s-]?FREE|\bTF\b")
_TAX_FREE_SYMBOL = re.compile(r"TF$")
_COUPON_IN_NAME = re.compile(r"^(\d+(?:\.\d+)?)%")


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
    bhav_date: date | None = None
    bhav_error: str | None = None


def _row(**values) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(values)
    return row


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
        if not market.ISIN_RE.match(isin) or not symbol or not issuer:
            result.skipped += 1
            continue
        coupon = _coupon(values[6])
        maturity = market.parse_date(values[9])
        name = _bond_name(issuer, coupon, maturity, symbol)
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


# --- Merge / build -------------------------------------------------------------


def merge_rows(by_source: dict[str, list[dict]], seen: dict[str, date]) -> list[dict]:
    return market.merge_by_isin(by_source, seen, SOURCES, COLUMNS, ("name",))


def build_rows(sources: Sources, today: date) -> tuple[list[dict], dict[str, int], int, dict]:
    """Parse and merge. Returns (rows, parsed counts per source, skipped, errors/dates)."""
    parsed: dict[str, SourceRows] = {"debt": parse_debt(sources.debt)}
    seen = {"debt": today}
    errors: dict[str, str | None] = {"bhav": sources.bhav_error}
    dates: dict[str, date | None] = {"bhav": None}
    market.parse_optional(
        "bhav", sources.bhav, lambda d: parse_nse_bhav(market.unzip_first(d)), errors, dates, parsed, seen
    )
    if not parsed["debt"].rows:
        raise ValueError("debt file contained no usable rows")
    rows = merge_rows({k: v.rows for k, v in parsed.items()}, seen)
    counts = {k: len(v.rows) for k, v in parsed.items()}
    skipped = sum(v.skipped for v in parsed.values())
    return rows, counts, skipped, {"errors": errors, "dates": dates}


def is_grace_row(nse_symbol: str | None, nse_series: str | None) -> bool:
    return market.is_grace_row(nse_symbol, nse_series, BHAV_SERIES)


def import_bonds(session: Session, sources: Sources, today: date) -> BondImportResult:
    """Upsert every merged row; unseen rows become inactive (SGBs after a grace period). Never deletes."""
    rows, counts, skipped, extra = build_rows(sources, today)
    stats = market.upsert_master(
        session, BondMaster, rows, COLUMNS + ["last_seen", "is_active"], BHAV_SERIES, today
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
        bhav_date=extra["dates"]["bhav"],
        bhav_error=extra["errors"]["bhav"],
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
