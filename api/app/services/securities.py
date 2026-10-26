"""Listed securities master (stocks, ETFs, bonds) from NSE and BSE files.

Sources (all pure parsers, malformed rows are counted in `skipped`, never raised):
  equity  NSE EQUITY_L.csv            kind=stock   (header names have leading spaces)
  etf     NSE eq_etfseclist.csv       kind=etf
  debt    NSE DEBT.csv                kind=bond    (15 columns; the ISIN column has no header)
  bhav    NSE UDiFF CM bhavcopy zip   SM/ST -> stock (SME), GB -> bond/sgb; other series ignored
  bse     BSE UDiFF CM bhavcopy       kind=stock/etf, optional (failure is reported, not fatal)

Rows are merged by ISIN: the highest-priority source (equity/etf/debt, then bhav, then bse) wins
for kind and name; other sources only fill fields that are still empty.
"""

import csv
import io
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

from app.models.security import Security

EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
DEBT_URL = "https://nsearchives.nseindia.com/content/equities/DEBT.csv"
NSE_BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
BSE_BHAV_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date}_F_0000.CSV"
BSE_REFERER = "https://www.bseindia.com/"
FETCH_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
WALK_BACK_DAYS = 7
STALE_DAYS = 30
BATCH_SIZE = 2000
GOVERNMENT_ISSUER = "Government of India"
BHAV_SERIES = {"SM": "stock", "ST": "stock", "GB": "bond"}
BHAV_GRACE_SERIES = tuple(BHAV_SERIES)
LAST_SEEN_REFRESH_DAYS = 7
BSE_SKIPPED_GROUPS = {"G"}  # government securities are covered by NSE DEBT

_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_MONTH_NAMES = [m.capitalize() for m in _MONTHS]
_TAX_FREE_TEXT = re.compile(r"TAX[\s-]?FREE|\bTF\b")
_TAX_FREE_SYMBOL = re.compile(r"TF$")
_COUPON_IN_NAME = re.compile(r"^(\d+(?:\.\d+)?)%")

COLUMNS = [
    "isin", "kind", "name", "nse_symbol", "nse_series", "bse_code", "bse_symbol", "bse_group",
    "face_value", "coupon_rate", "maturity_date", "issuer", "bond_type",
]  # fmt: skip
# Fill order for merging; lower index wins.
SOURCES = ["equity", "etf", "debt", "bhav", "bse"]


@dataclass
class SourceRows:
    rows: list[dict] = field(default_factory=list)
    skipped: int = 0


@dataclass
class Sources:
    """Raw downloaded files. bhav/bse carry the file date they were found for."""

    equity: bytes | str
    etf: bytes | str
    debt: bytes | str
    bhav: tuple[date, bytes] | None = None
    bhav_error: str | None = None
    bse: tuple[date, bytes | str] | None = None
    bse_error: str | None = None


@dataclass(frozen=True)
class ImportResult:
    sources: dict[str, int]  # parsed rows per source
    kinds: dict[str, int]  # merged rows per kind
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    skipped: int
    last_seen_refreshed: int = 0  # grace rows whose last_seen was moved forward
    bhav_date: date | None = None
    bse_date: date | None = None
    bhav_error: str | None = None
    bse_error: str | None = None


# --- Normalisation -------------------------------------------------------------


def _text(data: bytes | str) -> str:
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    return data.lstrip("﻿")


def _s(value: str | None) -> str:
    return (value or "").strip()


def _opt(value: str | None, limit: int) -> str | None:
    value = _s(value)
    return value[:limit] if value else None


def _decimal(value: str | None, places: str, upper: int) -> Decimal | None:
    try:
        number = Decimal(_s(value)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and 0 <= number < upper else None


def _face_value(value: str | None) -> Decimal | None:
    return _decimal(value, "0.01", 10**12)


def _coupon(value: str | None) -> Decimal | None:
    return _decimal(value, "0.001", 1000)


def _parse_date(value: str | None) -> date | None:
    """`25-JUN-2031` (also `25-Jun-31`) -> date."""
    parts = _s(value).split("-")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[2])
        if year < 100:
            year += 2000
        return date(year, _MONTHS[parts[1].lower()], int(parts[0]))
    except (KeyError, ValueError):
        return None


def derive_bond_type(series: str | None, symbol: str | None, name: str | None, issuer: str | None) -> str:
    """NSE debt series/name -> app bond type."""
    series = _s(series).upper()
    if series in ("GS", "TB", "SG"):
        return "government"
    if series == "GB":
        return "sgb"
    text = f"{_s(name)} {_s(issuer)}".upper()
    if _TAX_FREE_TEXT.search(text) or _TAX_FREE_SYMBOL.search(_s(symbol).upper()):
        return "tax_free"
    return "corporate"


def _row(**values) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(values)
    return row


def _records(data: bytes | str):
    """Yield dicts keyed by stripped header names; short rows simply lack the missing keys."""
    reader = csv.reader(io.StringIO(_text(data)))
    names = [h.strip() for h in next(reader, [])]
    for values in reader:
        if any(v.strip() for v in values):
            yield dict(zip(names, values, strict=False))


# --- Parsers -------------------------------------------------------------------


def parse_equity(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in _records(data):
        isin, symbol, name = _s(rec.get("ISIN NUMBER")), _s(rec.get("SYMBOL")), _s(rec.get("NAME OF COMPANY"))
        if not _ISIN.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="stock", name=name[:300], nse_symbol=symbol[:50],
                nse_series=_opt(rec.get("SERIES"), 10), face_value=_face_value(rec.get("FACE VALUE")),
            )  # fmt: skip
        )
    return result


def parse_etf(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in _records(data):
        isin, symbol, name = _s(rec.get("ISINNumber")), _s(rec.get("Symbol")), _s(rec.get("SecurityName"))
        if not _ISIN.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="etf", name=name[:300], nse_symbol=symbol[:50],
                nse_series="EQ", face_value=_face_value(rec.get("FaceValue")),
            )  # fmt: skip
        )
    return result


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
    reader = csv.reader(io.StringIO(_text(data)))
    next(reader, None)
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        if len(values) < 15:
            result.skipped += 1
            continue
        symbol, issuer, series = _s(values[0]), _s(values[1]), _s(values[2])
        isin = _s(values[14])
        if not _ISIN.match(isin) or not symbol or not issuer:
            result.skipped += 1
            continue
        coupon = _coupon(values[6])
        maturity = _parse_date(values[9])
        name = _bond_name(issuer, coupon, maturity, symbol)
        result.rows.append(
            _row(
                isin=isin, kind="bond", name=name, nse_symbol=symbol[:50], nse_series=series[:10] or None,
                face_value=_face_value(values[3]), coupon_rate=coupon, maturity_date=maturity,
                issuer=issuer[:300], bond_type=derive_bond_type(series, symbol, name, issuer),
            )  # fmt: skip
        )
    return result


def parse_nse_bhav(data: bytes | str) -> SourceRows:
    """NSE UDiFF CM bhavcopy CSV text: keep SME stocks (SM/ST) and gold bonds (GB)."""
    result = SourceRows()
    for rec in _records(data):
        series = _s(rec.get("SctySrs")).upper()
        kind = BHAV_SERIES.get(series)
        if kind is None:
            continue
        isin, symbol, name = _s(rec.get("ISIN")), _s(rec.get("TckrSymb")), _s(rec.get("FinInstrmNm"))
        if not _ISIN.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        extra = {}
        if kind == "bond":
            match = _COUPON_IN_NAME.match(name)
            extra = {
                "issuer": GOVERNMENT_ISSUER,
                "bond_type": "sgb",
                "coupon_rate": _coupon(match.group(1)) if match else None,
            }
        result.rows.append(
            _row(isin=isin, kind=kind, name=name[:300], nse_symbol=symbol[:50], nse_series=series, **extra)
        )
    return result


def parse_bse_bhav(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in _records(data):
        group = _s(rec.get("SctySrs")).upper()
        if group in BSE_SKIPPED_GROUPS:
            continue
        isin, code, name = _s(rec.get("ISIN")), _s(rec.get("FinInstrmId")), _s(rec.get("FinInstrmNm"))
        if not _ISIN.match(isin) or not code or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="etf" if isin.startswith("INF") else "stock", name=name[:300],
                bse_code=code[:10], bse_symbol=_opt(rec.get("TckrSymb"), 50), bse_group=group[:10] or None,
            )  # fmt: skip
        )
    return result


def unzip_first(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("bhavcopy zip contains no CSV")
        return archive.read(names[0])


# --- Merge ---------------------------------------------------------------------


def merge_rows(by_source: dict[str, list[dict]], seen: dict[str, date]) -> list[dict]:
    """Merge by ISIN. `seen[source]` is the file date; the row's last_seen is the latest of its sources."""
    merged: dict[str, dict] = {}
    for source in SOURCES:
        for row in by_source.get(source, []):
            current = merged.get(row["isin"])
            if current is None:
                current = dict(row, last_seen=seen[source], is_active=True)
                merged[row["isin"]] = current
                continue
            for column in COLUMNS:
                if column not in ("kind", "name") and current[column] is None:
                    current[column] = row[column]
            current["last_seen"] = max(current["last_seen"], seen[source])
    return list(merged.values())


def build_rows(sources: Sources, today: date) -> tuple[list[dict], dict[str, int], int, dict]:
    """Parse and merge. Returns (rows, parsed counts per source, skipped, errors)."""
    parsed: dict[str, SourceRows] = {
        "equity": parse_equity(sources.equity),
        "etf": parse_etf(sources.etf),
        "debt": parse_debt(sources.debt),
    }
    seen = {"equity": today, "etf": today, "debt": today}
    errors: dict[str, str | None] = {"bhav": sources.bhav_error, "bse": sources.bse_error}
    dates: dict[str, date | None] = {"bhav": None, "bse": None}
    optional = {
        "bhav": (sources.bhav, lambda d: parse_nse_bhav(unzip_first(d))),  # type: ignore[arg-type]
        "bse": (sources.bse, parse_bse_bhav),
    }
    for name, (payload, parser) in optional.items():
        if payload is None:
            continue
        file_date, data = payload
        try:
            result = parser(data)
            if not result.rows:
                raise ValueError(f"{name} file contained no usable rows")
        except Exception as exc:  # noqa: BLE001 - optional sources must never abort the import
            errors[name] = f"{type(exc).__name__}: {exc}"[:300]
            continue
        parsed[name] = result
        seen[name] = file_date
        dates[name] = file_date
    for required in ("equity", "etf", "debt"):
        if not parsed[required].rows:
            raise ValueError(f"{required} file contained no usable rows")
    rows = merge_rows({k: v.rows for k, v in parsed.items()}, seen)
    counts = {k: len(v.rows) for k, v in parsed.items()}
    skipped = sum(v.skipped for v in parsed.values())
    return rows, counts, skipped, {"errors": errors, "dates": dates}


# --- Fetch ---------------------------------------------------------------------


def _fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
        return response.read()


def is_html(data: bytes) -> bool:
    return data.lstrip()[:1] == b"<"


def fetch_latest_dated(
    template: str, today: date, headers: dict[str, str] | None = None
) -> tuple[date, bytes]:
    """Walk back from today (up to WALK_BACK_DAYS) to the latest published daily file; 404 = no file."""
    last_error: Exception | None = None
    for offset in range(WALK_BACK_DAYS + 1):
        day = today - timedelta(days=offset)
        try:
            data = _fetch(template.format(date=day.strftime("%Y%m%d")), headers)
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404):
                raise
            last_error = exc
            continue
        if is_html(data):  # BSE answers a missing file with its HTML shell and status 200
            last_error = LookupError("HTML page instead of a file")
            continue
        return day, data
    raise LookupError(f"no file in the last {WALK_BACK_DAYS + 1} days ({last_error})")


def fetch_sources(today: date) -> Sources:
    sources = Sources(equity=_fetch(EQUITY_URL), etf=_fetch(ETF_URL), debt=_fetch(DEBT_URL))
    try:
        sources.bhav = fetch_latest_dated(NSE_BHAV_URL, today)
    except Exception as exc:  # noqa: BLE001
        sources.bhav_error = f"{type(exc).__name__}: {exc}"[:300]
    try:
        sources.bse = fetch_latest_dated(BSE_BHAV_URL, today, {"Referer": BSE_REFERER})
    except Exception as exc:  # noqa: BLE001
        sources.bse_error = f"{type(exc).__name__}: {exc}"[:300]
    return sources


# --- Import --------------------------------------------------------------------


def is_grace_row(nse_symbol: str | None, nse_series: str | None) -> bool:
    """Rows from daily files that can be missing (NSE bhav SM/ST/GB, BSE-only) get a last_seen grace."""
    return nse_symbol is None or (nse_series or "") in BHAV_GRACE_SERIES


def import_securities(session: Session, sources: Sources, today: date) -> ImportResult:
    """Upsert every merged row; unseen rows become inactive (SME/SGB after a grace period). Never deletes."""
    rows, counts, skipped, extra = build_rows(sources, today)
    table = Security.__table__
    columns = COLUMNS + ["last_seen", "is_active"]
    # last_seen is written on insert only; it is refreshed separately (weekly resolution) below.
    data_columns = [c for c in columns if c not in ("isin", "last_seen")]
    inserted = updated = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = [{c: row[c] for c in columns} for row in rows[start:start + BATCH_SIZE]]
        statement = pg_insert(Security).values(batch)
        update = {c: statement.excluded[c] for c in data_columns}
        update["updated_at"] = sa.func.now()
        statement = statement.on_conflict_do_update(
            index_elements=["isin"],
            set_=update,
            where=sa.tuple_(*[table.c[c] for c in data_columns]).is_distinct_from(
                sa.tuple_(*[statement.excluded[c] for c in data_columns])
            ),
        ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
        for (was_inserted,) in session.execute(statement):
            if was_inserted:
                inserted += 1
            else:
                updated += 1

    grace_rows = [r for r in rows if is_grace_row(r["nse_symbol"], r["nse_series"])]
    last_seen_refreshed = session.execute(
        sa.text(
            "UPDATE securities s SET last_seen = v.seen "
            "FROM unnest(:isins, :seen) AS v(isin, seen) "
            "WHERE s.isin = v.isin AND (s.last_seen IS NULL OR s.last_seen < v.seen - :days)"
        ).bindparams(
            sa.bindparam("isins", value=[r["isin"] for r in grace_rows], type_=ARRAY(sa.String)),
            sa.bindparam("seen", value=[r["last_seen"] for r in grace_rows], type_=ARRAY(sa.Date)),
            sa.bindparam("days", value=LAST_SEEN_REFRESH_DAYS, type_=sa.Integer),
        )
    ).rowcount

    # Rows from the always-required lists (NSE symbol, non-grace series) deactivate immediately;
    # grace rows (bhav SM/ST/GB, BSE-only) only once last_seen is older than STALE_DAYS.
    deactivated = session.execute(
        sa.text(
            "UPDATE securities SET is_active = false, updated_at = now() "
            "WHERE is_active AND isin <> ALL(:isins) AND ("
            "(nse_symbol IS NOT NULL AND COALESCE(nse_series, '') <> ALL(:grace_series)) "
            "OR last_seen IS NULL OR last_seen < :cutoff)"
        ).bindparams(
            sa.bindparam("isins", value=[r["isin"] for r in rows], type_=ARRAY(sa.String)),
            sa.bindparam("grace_series", value=list(BHAV_GRACE_SERIES), type_=ARRAY(sa.String)),
            sa.bindparam("cutoff", value=today - timedelta(days=STALE_DAYS), type_=sa.Date),
        )
    ).rowcount
    session.commit()

    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    return ImportResult(
        sources=counts,
        kinds=kinds,
        total=len(rows),
        inserted=inserted,
        updated=updated,
        unchanged=len(rows) - inserted - updated,
        deactivated=deactivated,
        skipped=skipped,
        last_seen_refreshed=last_seen_refreshed,
        bhav_date=extra["dates"]["bhav"],
        bse_date=extra["dates"]["bse"],
        bhav_error=extra["errors"]["bhav"],
        bse_error=extra["errors"]["bse"],
    )


# --- Lookup / search -----------------------------------------------------------

UNKNOWN_STOCK_MESSAGE = "Select a stock from the list"
UNKNOWN_BOND_MESSAGE = "Select a bond from the list"
_SYMBOL = re.compile(r"^[A-Z0-9&-]{1,20}$")


def get_security(session: Session, security_id: int) -> Security | None:
    if not 1 <= security_id <= 2**31 - 1:
        return None
    return session.get(Security, security_id)


def require_security(
    session: Session, security_id: int, kinds: tuple[str, ...], message: str
) -> Security:
    """Used by stock/bond create/update: unknown id or wrong kind -> 422 on `security_id`."""
    security = get_security(session, security_id)
    if security is None or security.kind not in kinds:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "security_id"), "msg": message, "input": security_id}]
        )
    return security


def pick_stock_symbol(security: Security, exchange: str, payload_symbol: str | None) -> str | None:
    """NSE symbol on NSE (else the BSE symbol), BSE symbol on BSE, else the payload's.

    Candidates that do not satisfy the app's symbol pattern are skipped, never rejected.
    """
    candidates = [security.nse_symbol, security.bse_symbol] if exchange == "NSE" else [security.bse_symbol]
    for candidate in candidates:
        if candidate and _SYMBOL.match(candidate.strip().upper()):
            return candidate.strip().upper()
    return payload_symbol


def search_securities(
    session: Session, q: str, kinds: tuple[str, ...], limit: int = 20
) -> list[Security]:
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = sa.select(Security).where(Security.is_active, Security.kind.in_(kinds))
    for token in q.split():
        statement = statement.where(
            sa.or_(
                Security.name.icontains(token, autoescape=True),
                Security.nse_symbol.icontains(token, autoescape=True),
                Security.bse_symbol.icontains(token, autoescape=True),
                Security.bse_code.icontains(token, autoescape=True),
                Security.isin.icontains(token, autoescape=True),
                Security.issuer.icontains(token, autoescape=True),
            )
        )
    statement = statement.order_by(
        sa.func.similarity(sa.func.lower(Security.name), q.strip().lower()).desc(),
        Security.name,
        Security.id,
    ).limit(limit)
    return list(session.scalars(statement))
