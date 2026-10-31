"""Closing prices of HELD stocks (stocks.master_id set, any user) in `stock_price_history`.

Daily: the securities import appends today's close for held stocks. Once per stock: a 12-month
month-end backfill from past NSE (fallback BSE) bhavcopies, recorded in `stock_price_history_sync`.
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.stock_master import StockMaster
from app.models.stock_price_history import StockPriceHistory, StockPriceHistorySync
from app.services import market_files as market

log = logging.getLogger(__name__)
BATCH = 2000


@dataclass
class BackfillResult:
    stocks: int = 0  # stocks backfilled (sync rows written)
    rows: int = 0  # history rows inserted
    months_fetched: int = 0
    months_missed: int = 0
    errors: list[str] = field(default_factory=list)


# --- Pure helpers --------------------------------------------------------------


def month_ends(today: date, months: int = 12) -> list[date]:
    """Last calendar day of each of the `months` months before today's month, oldest first."""
    result: list[date] = []
    last = today.replace(day=1) - timedelta(days=1)
    for _ in range(months):
        result.append(last)
        last = last.replace(day=1) - timedelta(days=1)
    return result[::-1]


def rows_for_held(
    closes: dict[str, dict[str, Any]], held: dict[str, int], trade_date: date | None = None
) -> list[dict]:
    """History rows for held ISINs ({isin: master_id}) from {isin: {price, trade_date}}.

    `trade_date` overrides the per-row date (used for backfill, where the file date is the truth).
    """
    return [
        {
            "master_id": held[isin],
            "trade_date": trade_date or c["trade_date"],
            "close": c["price"],
        }
        for isin, c in closes.items()
        if isin in held and c.get("price")
    ]


def split_by_source(
    needed: dict[str, int], nse: dict[str, dict]
) -> tuple[dict[str, int], dict[str, int]]:
    """Split needed ISINs into (found in the NSE file, still missing -> try BSE)."""
    found = {i: m for i, m in needed.items() if i in nse}
    missing = {i: m for i, m in needed.items() if i not in nse}
    return found, missing


# --- DB ------------------------------------------------------------------------


def held_stocks(session: Session) -> dict[str, int]:
    """{isin: master_id} for stock_master rows held by any user."""
    rows = session.execute(
        sa.select(StockMaster.isin, StockMaster.id)
        .where(StockMaster.id.in_(sa.select(Stock.master_id).where(Stock.master_id.is_not(None))))
    ).all()
    return {isin: mid for isin, mid in rows}


def _insert(session: Session, values: list[dict]) -> int:
    inserted = 0
    for start in range(0, len(values), BATCH):
        statement = (
            pg_insert(StockPriceHistory)
            .values(values[start : start + BATCH])
            .on_conflict_do_nothing(index_elements=["master_id", "trade_date"])
            .returning(StockPriceHistory.master_id)
        )
        inserted += len(session.execute(statement).all())
    return inserted


def append_closes_for_holdings(session: Session, closes: dict[str, dict[str, Any]]) -> int:
    """Store the bhavcopy close ({isin: {price, trade_date}}) of held stocks. Commits; returns rows inserted."""
    if not closes:
        return 0
    values = rows_for_held(closes, held_stocks(session))
    inserted = _insert(session, values) if values else 0
    session.commit()
    return inserted


def _fetch_closes(template: str, day: date, headers: dict | None, zipped: bool) -> tuple[date, dict]:
    from app.services.stock_master import parse_closes  # stock_master imports this module

    file_date, data = market.fetch_latest_dated(template, day, headers)
    if zipped:
        data = market.unzip_first(data)
    return file_date, parse_closes(data, file_date)


def backfill_month_ends(session: Session, today: date, months: int = 12) -> BackfillResult:
    """Backfill month-end closes for held stocks without a sync row. Commits."""
    result = BackfillResult()
    held = held_stocks(session)
    done = set(session.scalars(sa.select(StockPriceHistorySync.master_id)))
    needed = {isin: mid for isin, mid in held.items() if mid not in done}
    if not needed:
        return result
    for month_end in month_ends(today, months):
        values: list[dict] = []
        remaining = dict(needed)
        try:
            file_date, nse = _fetch_closes(market.NSE_BHAV_URL, month_end, None, True)
            found, remaining = split_by_source(needed, nse)
            values += rows_for_held(nse, found, file_date)
        except Exception as exc:  # noqa: BLE001 - a missing month must not fail the import
            result.errors.append(f"NSE {month_end}: {type(exc).__name__}: {exc}"[:200])
        if remaining:
            try:
                file_date, bse = _fetch_closes(
                    market.BSE_BHAV_URL, month_end, {"Referer": market.BSE_REFERER}, False
                )
                values += rows_for_held(bse, remaining, file_date)
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"BSE {month_end}: {type(exc).__name__}: {exc}"[:200])
        if not values:
            result.months_missed += 1
            log.warning("no closes for month end %s", month_end)
            continue
        result.months_fetched += 1
        result.rows += _insert(session, values)
        session.commit()
    if result.months_fetched:
        now = datetime.now(UTC)
        session.execute(
            pg_insert(StockPriceHistorySync)
            .values([{"master_id": mid, "backfilled_at": now} for mid in needed.values()])
            .on_conflict_do_nothing(index_elements=["master_id"])
        )
        session.commit()
        result.stocks = len(needed)
    return result


def backfill_safely(session: Session, today: date, months: int = 12) -> BackfillResult | None:
    """backfill_month_ends for the import flows: a failure is logged and never breaks the import."""
    try:
        return backfill_month_ends(session, today, months)
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.warning("stock history backfill failed: %s", exc)
        return None


def closes_between(
    session: Session, master_ids: Iterable[int], start: date, end: date
) -> dict[int, list[tuple[date, Decimal]]]:
    """Stored closes per master_id within [start, end], sorted by date."""
    ids = set(master_ids)
    out: dict[int, list[tuple[date, Decimal]]] = {}
    if not ids:
        return out
    rows = session.execute(
        sa.select(
            StockPriceHistory.master_id, StockPriceHistory.trade_date, StockPriceHistory.close
        )
        .where(
            StockPriceHistory.master_id.in_(ids),
            StockPriceHistory.trade_date >= start,
            StockPriceHistory.trade_date <= end,
        )
        .order_by(StockPriceHistory.master_id, StockPriceHistory.trade_date)
    ).all()
    for master_id, trade_date, close in rows:
        out.setdefault(master_id, []).append((trade_date, close))
    return out
