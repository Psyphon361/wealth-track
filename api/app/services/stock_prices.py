"""Last stock prices: Yahoo quotes on demand, daily bhavcopy close as backup.

`ensure_fresh` refreshes only stale rows of `stock_price_latest`, in parallel and within a time
budget; network failures keep the old row. Market hours are 09:15-15:30 IST Mon-Fri (holidays ignored).
"""

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.app_state import AppState
from app.models.stock_master import StockMaster
from app.models.stock_price import StockPriceLatest

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
LIVE_MAX_AGE = timedelta(minutes=15)
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
REQUEST_TIMEOUT = 4
MAX_WORKERS = 8
BLOCK_KEY = "yahoo_blocked_until"
BLOCK_FOR = timedelta(minutes=15)
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Quote:
    price: Decimal
    prev_close: Decimal | None
    price_time: datetime | None


FetchQuote = Callable[[str], "Quote | None"]


def _money(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and 0 <= number < Decimal(10) ** 12 else None


def yahoo_symbol(master: Any) -> str | None:
    if master.nse_symbol:
        return f"{master.nse_symbol}.NS"
    if master.bse_symbol:
        return f"{master.bse_symbol}.BO"
    return None


def parse_yahoo_chart(payload: Any) -> Quote | None:
    """Quote from a Yahoo v8 chart response; None when there is no usable price."""
    try:
        meta = payload["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    price = _money(meta.get("regularMarketPrice"))
    if price is None or price <= 0:
        return None
    prev = _money(meta.get("previousClose"))
    if prev is None:
        prev = _money(meta.get("chartPreviousClose"))
    price_time = None
    stamp = meta.get("regularMarketTime")
    if isinstance(stamp, int | float) and not isinstance(stamp, bool):
        try:
            price_time = datetime.fromtimestamp(stamp, UTC)
        except (OverflowError, OSError, ValueError):
            price_time = None
    return Quote(price=price, prev_close=prev, price_time=price_time)


def fetch_yahoo_quote(symbol: str) -> Quote | None:
    request = urllib.request.Request(
        YAHOO_URL.format(symbol=symbol), headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:  # noqa: S310
        return parse_yahoo_chart(json.loads(response.read()))


def day_change_pct(price: Decimal | None, prev_close: Decimal | None) -> Decimal | None:
    if price is None or not prev_close:
        return None
    return ((Decimal(price) - Decimal(prev_close)) / Decimal(prev_close) * 100).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )


# --- Staleness -----------------------------------------------------------------


def _last_close(now: datetime) -> datetime:
    """Most recent weekday 15:30 IST at or before `now`."""
    local = now.astimezone(IST)
    day = local.date()
    if local.time() < MARKET_CLOSE:
        day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return datetime.combine(day, MARKET_CLOSE, IST)


def is_stale(
    fetched_at: datetime | None, now: datetime, last_attempt_at: datetime | None = None
) -> bool:
    """Stale judged on the later of the last fetch and the last (failed) attempt."""
    seen = [t for t in (fetched_at, last_attempt_at) if t is not None]
    if not seen:
        return True
    fetched_at = max(seen)
    local = now.astimezone(IST)
    in_hours = local.weekday() < 5 and MARKET_OPEN <= local.time() < MARKET_CLOSE
    if in_hours:
        return now - fetched_at > LIVE_MAX_AGE
    return fetched_at < _last_close(now)


# --- Store ---------------------------------------------------------------------


def latest_prices(session: Session, master_ids: Iterable[int]) -> dict[int, StockPriceLatest]:
    ids = set(master_ids)
    if not ids:
        return {}
    return {r.master_id: r for r in _rows(session, ids) if r.price is not None}


def _rows(session: Session, ids: set[int]) -> list[StockPriceLatest]:
    return list(
        session.scalars(
            sa.select(StockPriceLatest).where(StockPriceLatest.master_id.in_(ids))
        ).all()
    )


def blocked_until(session: Session) -> datetime | None:
    state = session.get(AppState, BLOCK_KEY)
    if state is None:
        return None
    try:
        return datetime.fromisoformat(state.value)
    except ValueError:
        return None


def _set_blocked(session: Session, until: datetime) -> None:
    statement = pg_insert(AppState).values(key=BLOCK_KEY, value=until.isoformat())
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": statement.excluded.value, "updated_at": sa.func.now()},
        )
    )
    session.commit()


class _Blocked(Exception):
    """Yahoo answered 429; stop requesting."""


def ensure_fresh(
    session: Session,
    master_ids: Iterable[int],
    budget_s: float = 3.0,
    *,
    fetch: FetchQuote = fetch_yahoo_quote,
    now: datetime | None = None,
) -> None:
    """Refresh stale prices from Yahoo within `budget_s`; failures keep the old row. Commits."""
    ids = set(master_ids)
    if not ids:
        return
    now = now or datetime.now(UTC)
    until = blocked_until(session)
    if until is not None and now < until:
        return
    existing = {r.master_id: r for r in _rows(session, ids)}
    stale = [
        i
        for i in ids
        if is_stale(
            getattr(existing.get(i), "fetched_at", None),
            now,
            getattr(existing.get(i), "last_attempt_at", None),
        )
    ]
    if not stale:
        return
    masters = session.scalars(sa.select(StockMaster).where(StockMaster.id.in_(stale))).all()
    symbols = {m.id: s for m in masters if (s := yahoo_symbol(m))}
    if not symbols:
        return

    blocked = Event()

    def run(symbol: str) -> Quote | None:
        if blocked.is_set():
            raise _Blocked
        try:
            return fetch(symbol)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                blocked.set()
                raise _Blocked from exc
            log.warning("price fetch failed for %s: %s", symbol, exc)
            return None
        except Exception as exc:  # noqa: BLE001 - a missing quote must never break a page
            log.warning("price fetch failed for %s: %s", symbol, exc)
            return None

    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    try:
        futures = {pool.submit(run, symbol): mid for mid, symbol in symbols.items()}
        done, pending = wait(futures, timeout=budget_s)
        results: dict[int, Quote | None] = {}
        for f in done:
            if f.exception() is None:
                results[futures[f]] = f.result()
        timed_out = [futures[f] for f in pending]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    if blocked.is_set():
        log.warning("Yahoo answered 429; pausing price requests for %s", BLOCK_FOR)
        _set_blocked(session, now + BLOCK_FOR)
        timed_out = []  # the cooldown covers everything not fetched
        results = {mid: q for mid, q in results.items() if q is not None}

    # Failed or timed-out fetches record an attempt so they are not retried until stale again.
    failed = [mid for mid, q in results.items() if q is None] + timed_out
    if failed:
        attempt = pg_insert(StockPriceLatest).values(
            [{"master_id": mid, "source": "yahoo", "last_attempt_at": now} for mid in failed]
        )
        session.execute(
            attempt.on_conflict_do_update(
                index_elements=["master_id"], set_={"last_attempt_at": attempt.excluded.last_attempt_at}
            )
        )
        session.commit()

    values = [
        {
            "master_id": mid,
            "price": q.price,
            "prev_close": q.prev_close,
            "price_time": q.price_time,
            "source": "yahoo",
            "fetched_at": now,
        }
        for mid, q in results.items()
        if q is not None
    ]
    if not values:
        return
    statement = pg_insert(StockPriceLatest).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["master_id"],
        set_={c: statement.excluded[c] for c in values[0] if c != "master_id"},
    )
    session.execute(statement)
    session.commit()


def close_time(trade_date: date) -> datetime:
    return datetime.combine(trade_date, MARKET_CLOSE, IST)


def upsert_closes(session: Session, closes: dict[str, dict[str, Any]]) -> int:
    """Store bhavcopy closes ({isin: {price, prev_close, trade_date}}) as the backup price.

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
            "fetched_at": datetime.now(UTC),
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
