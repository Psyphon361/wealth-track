"""Last stock prices: the nightly NSE/BSE bhavcopy close, stored in `stock_price_latest`.

Written by the securities import (`app.services.stock_master`); read by the holdings endpoints.
"""

from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.stock_master import StockMaster
from app.models.stock_price import StockPriceLatest

IST = ZoneInfo("Asia/Kolkata")
MARKET_CLOSE = time(15, 30)
_CENT = Decimal("0.01")


def day_change_pct(price: Decimal | None, prev_close: Decimal | None) -> Decimal | None:
    if price is None or not prev_close:
        return None
    return ((Decimal(price) - Decimal(prev_close)) / Decimal(prev_close) * 100).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )


def latest_prices(session: Session, master_ids: Iterable[int]) -> dict[int, StockPriceLatest]:
    ids = set(master_ids)
    if not ids:
        return {}
    rows = session.scalars(
        sa.select(StockPriceLatest).where(StockPriceLatest.master_id.in_(ids))
    ).all()
    return {r.master_id: r for r in rows if r.price is not None}


def close_time(trade_date: date) -> datetime:
    return datetime.combine(trade_date, MARKET_CLOSE, IST)


def upsert_closes(session: Session, closes: dict[str, dict[str, Any]]) -> int:
    """Store bhavcopy closes ({isin: {price, prev_close, trade_date}}).

    A row is written only when none exists or its price_time is older than the close. Commits.
    """
    if not closes:
        return 0
    master_ids = dict(session.execute(sa.select(StockMaster.isin, StockMaster.id)).all())
    values = [
        {
            "master_id": master_ids[isin],
            "price": c["price"],
            "prev_close": c.get("prev_close"),
            "price_time": close_time(c["trade_date"]),
            "source": "bhavcopy",
            "updated_at": sa.func.now(),
        }
        for isin, c in closes.items()
        if isin in master_ids
    ]
    written = 0
    for start in range(0, len(values), 2000):
        statement = pg_insert(StockPriceLatest).values(values[start : start + 2000])
        statement = statement.on_conflict_do_update(
            index_elements=["master_id"],
            set_={c: statement.excluded[c] for c in values[0] if c != "master_id"},
            where=sa.or_(
                StockPriceLatest.price_time.is_(None),
                StockPriceLatest.price_time < statement.excluded.price_time,
            ),
        ).returning(StockPriceLatest.master_id)
        written += len(session.execute(statement).all())
    session.commit()
    return written
