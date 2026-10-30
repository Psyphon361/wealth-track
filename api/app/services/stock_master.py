"""Stock and ETF master (stock_master) from NSE and BSE files.

Sources (pure parsers; malformed rows are counted in `skipped`, never raised):
  equity  NSE EQUITY_L.csv            kind=stock   (header names have leading spaces)
  etf     NSE eq_etfseclist.csv       kind=etf
  bhav    NSE UDiFF CM bhavcopy zip   SM/ST (SME) -> stock; optional
  bse     BSE UDiFF CM bhavcopy       non-INF ISIN -> stock, INF -> etf; optional

Rows are merged by ISIN: the highest-priority source (equity/etf, then bhav, then bse) wins for
kind and name; other sources only fill fields that are still empty. BSE rows whose ISIN is in the
NSE debt list are bonds and are dropped here.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster
from app.services import market_files as market
from app.services import stock_prices
from app.services.market_files import SourceRows, Sources

BHAV_SERIES = ("SM", "ST")
BSE_SKIPPED_GROUPS = {"G"}  # government securities are covered by NSE DEBT
COLUMNS = [
    "isin", "kind", "name", "nse_symbol", "nse_series", "bse_code", "bse_symbol", "bse_group",
    "face_value",
]  # fmt: skip
SOURCES = ["equity", "etf", "bhav", "bse"]  # fill order; lower index wins
UNKNOWN_STOCK_MESSAGE = "Select a stock from the list"
_SYMBOL = re.compile(r"^[A-Z0-9&-]{1,20}$")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StockImportResult:
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


def _row(**values) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(values)
    return row


# --- Parsers -------------------------------------------------------------------


def parse_equity(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in market.records(data):
        isin, symbol, name = market.s(rec.get("ISIN NUMBER")), market.s(rec.get("SYMBOL")), market.s(rec.get("NAME OF COMPANY"))
        if not market.ISIN_RE.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="stock", name=name[:300], nse_symbol=symbol[:50],
                nse_series=market.opt(rec.get("SERIES"), 10), face_value=market.face_value(rec.get("FACE VALUE")),
            )  # fmt: skip
        )
    return result


def parse_etf(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in market.records(data):
        isin, symbol, name = market.s(rec.get("ISINNumber")), market.s(rec.get("Symbol")), market.s(rec.get("SecurityName"))
        if not market.ISIN_RE.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="etf", name=name[:300], nse_symbol=symbol[:50],
                nse_series="EQ", face_value=market.face_value(rec.get("FaceValue")),
            )  # fmt: skip
        )
    return result


def parse_nse_bhav(data: bytes | str) -> SourceRows:
    """NSE UDiFF CM bhavcopy CSV text: keep SME stocks (SM/ST); other series are ignored."""
    result = SourceRows()
    for rec in market.records(data):
        series = market.s(rec.get("SctySrs")).upper()
        if series not in BHAV_SERIES:
            continue
        isin, symbol, name = market.s(rec.get("ISIN")), market.s(rec.get("TckrSymb")), market.s(rec.get("FinInstrmNm"))
        if not market.ISIN_RE.match(isin) or not symbol or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(isin=isin, kind="stock", name=name[:300], nse_symbol=symbol[:50], nse_series=series)
        )
    return result


def parse_bse_bhav(data: bytes | str) -> SourceRows:
    result = SourceRows()
    for rec in market.records(data):
        group = market.s(rec.get("SctySrs")).upper()
        if group in BSE_SKIPPED_GROUPS:
            continue
        isin, code, name = market.s(rec.get("ISIN")), market.s(rec.get("FinInstrmId")), market.s(rec.get("FinInstrmNm"))
        if not market.ISIN_RE.match(isin) or not code or not name:
            result.skipped += 1
            continue
        result.rows.append(
            _row(
                isin=isin, kind="etf" if isin.startswith("INF") else "stock", name=name[:300],
                bse_code=code[:10], bse_symbol=market.opt(rec.get("TckrSymb"), 50), bse_group=group[:10] or None,
            )  # fmt: skip
        )
    return result


def _trade_date(value: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(market.s(value)[:10])
    except ValueError:
        return fallback


def parse_closes(data: bytes | str, fallback_date: date) -> dict[str, dict]:
    """Per-ISIN close from a UDiFF bhavcopy (NSE or BSE), all series: price, prev_close, trade_date."""
    closes: dict[str, dict] = {}
    for rec in market.records(data):
        isin = market.s(rec.get("ISIN"))
        price = market.decimal_value(rec.get("ClsPric"), "0.01", 10**12)
        if not market.ISIN_RE.match(isin) or not price:
            continue
        closes[isin] = {
            "price": price,
            "prev_close": market.decimal_value(rec.get("PrvsClsgPric"), "0.01", 10**12) or None,
            "trade_date": _trade_date(rec.get("TradDt"), fallback_date),
        }
    return closes


def collect_closes(sources: Sources) -> dict[str, dict]:
    """Closes from both bhavcopies; NSE wins over BSE for the same ISIN. Unparseable files are skipped."""
    closes: dict[str, dict] = {}
    if sources.bse:
        try:
            closes.update(parse_closes(sources.bse[1], sources.bse[0]))
        except Exception as exc:  # noqa: BLE001 - backup prices must never abort the import
            log.warning("BSE close prices skipped: %s", exc)
    if sources.bhav:
        try:
            closes.update(parse_closes(market.unzip_first(sources.bhav[1]), sources.bhav[0]))
        except Exception as exc:  # noqa: BLE001
            log.warning("NSE close prices skipped: %s", exc)
    return closes


# --- Merge / build -------------------------------------------------------------


def merge_rows(by_source: dict[str, list[dict]], seen: dict[str, date]) -> list[dict]:
    return market.merge_by_isin(by_source, seen, SOURCES, COLUMNS, ("kind", "name"))


def build_rows(sources: Sources, today: date) -> tuple[list[dict], dict[str, int], int, dict]:
    """Parse and merge. Returns (rows, parsed counts per source, skipped, errors/dates)."""
    parsed: dict[str, SourceRows] = {"equity": parse_equity(sources.equity), "etf": parse_etf(sources.etf)}
    seen = {"equity": today, "etf": today}
    errors: dict[str, str | None] = {"bhav": sources.bhav_error, "bse": sources.bse_error}
    dates: dict[str, date | None] = {"bhav": None, "bse": None}
    market.parse_optional(
        "bhav", sources.bhav, lambda d: parse_nse_bhav(market.unzip_first(d)), errors, dates, parsed, seen
    )
    market.parse_optional("bse", sources.bse, parse_bse_bhav, errors, dates, parsed, seen)
    for required in ("equity", "etf"):
        if not parsed[required].rows:
            raise ValueError(f"{required} file contained no usable rows")
    if "bse" in parsed:  # BSE lists some debt too; those belong to bond_master
        bonds = market.debt_isins(sources.debt)
        parsed["bse"].rows = [r for r in parsed["bse"].rows if r["isin"] not in bonds]
    rows = merge_rows({k: v.rows for k, v in parsed.items()}, seen)
    counts = {k: len(v.rows) for k, v in parsed.items()}
    skipped = sum(v.skipped for v in parsed.values())
    return rows, counts, skipped, {"errors": errors, "dates": dates}


def is_grace_row(nse_symbol: str | None, nse_series: str | None) -> bool:
    return market.is_grace_row(nse_symbol, nse_series, BHAV_SERIES)


def import_stocks(session: Session, sources: Sources, today: date) -> StockImportResult:
    """Upsert every merged row; unseen rows become inactive (SME after a grace period). Never deletes."""
    rows, counts, skipped, extra = build_rows(sources, today)
    stats = market.upsert_master(
        session, StockMaster, rows, COLUMNS + ["last_seen", "is_active"], BHAV_SERIES, today
    )
    try:
        stock_prices.upsert_closes(session, collect_closes(sources))
    except Exception as exc:  # noqa: BLE001 - backup prices must never fail the master import
        session.rollback()
        log.warning("close prices not stored: %s", exc)
    kinds: dict[str, int] = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    return StockImportResult(
        sources=counts,
        kinds=kinds,
        total=len(rows),
        inserted=stats.inserted,
        updated=stats.updated,
        unchanged=len(rows) - stats.inserted - stats.updated,
        deactivated=stats.deactivated,
        skipped=skipped,
        last_seen_refreshed=stats.last_seen_refreshed,
        bhav_date=extra["dates"]["bhav"],
        bse_date=extra["dates"]["bse"],
        bhav_error=extra["errors"]["bhav"],
        bse_error=extra["errors"]["bse"],
    )


# --- Lookup / search -----------------------------------------------------------


def get_stock_master(session: Session, master_id: int) -> StockMaster | None:
    if not 1 <= master_id <= 2**31 - 1:
        return None
    return session.get(StockMaster, master_id)


def require_stock_master(session: Session, master_id: int) -> StockMaster:
    """Used by stock create/update: unknown id -> 422 on `master_id`."""
    stock = get_stock_master(session, master_id)
    if stock is None:
        raise RequestValidationError(
            [{"type": "value_error", "loc": ("body", "master_id"), "msg": UNKNOWN_STOCK_MESSAGE, "input": master_id}]
        )
    return stock


def pick_stock_symbol(stock: StockMaster, exchange: str, payload_symbol: str | None) -> str | None:
    """NSE symbol on NSE (else the BSE symbol), BSE symbol on BSE, else the payload's.

    Candidates that do not satisfy the app's symbol pattern are skipped, never rejected.
    """
    candidates = [stock.nse_symbol, stock.bse_symbol] if exchange == "NSE" else [stock.bse_symbol]
    for candidate in candidates:
        if candidate and _SYMBOL.match(candidate.strip().upper()):
            return candidate.strip().upper()
    return payload_symbol


def search_stocks(session: Session, q: str, limit: int = 20) -> list[StockMaster]:
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = sa.select(StockMaster).where(StockMaster.is_active)
    for token in q.split():
        statement = statement.where(
            sa.or_(
                StockMaster.name.icontains(token, autoescape=True),
                StockMaster.nse_symbol.icontains(token, autoescape=True),
                StockMaster.bse_symbol.icontains(token, autoescape=True),
                StockMaster.bse_code.icontains(token, autoescape=True),
                StockMaster.isin.icontains(token, autoescape=True),
            )
        )
    statement = statement.order_by(
        sa.func.similarity(sa.func.lower(StockMaster.name), q.strip().lower()).desc(),
        StockMaster.name,
        StockMaster.id,
    ).limit(limit)
    return list(session.scalars(statement))
