"""Net worth over time: pure functions over plain data (no DB). The loader lives in the router."""

from bisect import bisect_right
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

from app.services import valuation

RANGES = ("1m", "6m", "1y", "all")
MAX_YEARS = 10
UNITS_TOLERANCE = Decimal("0.001")
_CENT = Decimal("0.01")

Series = Sequence[tuple[date, Decimal]]


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def on_or_before(series: Series, on_date: date) -> Decimal | None:
    """Value of the last (date, value) entry with date <= on_date; series sorted by date."""
    index = bisect_right([d for d, _ in series], on_date)
    return series[index - 1][1] if index else None


# --- Dates ---------------------------------------------------------------------


def range_start(range_key: str, today: date) -> date | None:
    """First day of a fixed range; None for "all"."""
    if range_key == "1m":
        return today - relativedelta(months=1)
    if range_key == "6m":
        return today - relativedelta(months=6)
    if range_key == "1y":
        return today - relativedelta(years=1)
    return None


def date_list(range_key: str, today: date, earliest: date | None) -> list[date]:
    """Dates to value, oldest first, always ending on today. "all" is weekly back from today."""
    start = range_start(range_key, today)
    if start is not None:
        return [start + timedelta(days=i) for i in range((today - start).days + 1)]
    if earliest is None:
        return [today]
    earliest = max(earliest, today - relativedelta(years=MAX_YEARS))
    days: list[date] = []
    d = today
    while d >= earliest:
        days.append(d)
        d -= timedelta(days=7)
    return days[::-1]


# --- Mutual funds --------------------------------------------------------------


def txns_match(mf: Any, txns: Sequence[Any]) -> bool:
    """True when the transactions exist and their net units equal the holding's units."""
    if not txns:
        return False
    net = sum(
        (Decimal(t.units) if t.kind == "purchase" else -Decimal(t.units) for t in txns),
        Decimal(0),
    )
    return abs(net - Decimal(mf.units)) <= UNITS_TOLERANCE


def sorted_txns(txns: Sequence[Any]) -> list[Any]:
    """Oldest first; purchases before redemptions on the same day."""
    return sorted(txns, key=lambda t: (t.txn_date, t.kind != "purchase"))


def units_and_cost_at(txns: Sequence[Any], on_date: date) -> tuple[Decimal, Decimal]:
    """(units held, FIFO cost of those units) after the transactions dated <= on_date.

    `txns` must be sorted with sorted_txns. Redemptions consume the oldest lots first.
    """
    lots: deque[list[Decimal]] = deque()  # [units, cost]
    for t in txns:
        if t.txn_date > on_date:
            break
        units = Decimal(t.units)
        if t.kind == "purchase":
            lots.append([units, abs(Decimal(t.amount))])
            continue
        remaining = units
        while remaining > 0 and lots:
            lot = lots[0]
            if lot[0] <= remaining:
                remaining -= lot[0]
                lots.popleft()
            else:
                lot[1] -= lot[1] * remaining / lot[0]
                lot[0] -= remaining
                remaining = Decimal(0)
    return (
        sum((lot[0] for lot in lots), Decimal(0)),
        sum((lot[1] for lot in lots), Decimal(0)),
    )


# --- Series --------------------------------------------------------------------


@dataclass
class _Mf:
    record: Any
    txns: list[Any] | None  # sorted transactions when they match the holding, else None
    start: date


def _holding_start(slug: str, record: Any) -> date:
    return {
        "fd": lambda r: r.start_date,
        "rd": lambda r: r.start_date,
        "stock": lambda r: r.buy_date,
        "bond": lambda r: r.purchase_date,
        "mf": lambda r: r.purchase_date,
        "gold": lambda r: r.purchase_date,
        "cash": lambda r: r.balance_date,
    }[slug](record)


def _prepare_mfs(mfs: Sequence[Any], txns: dict[int, Sequence[Any]]) -> list[_Mf]:
    out = []
    for mf in mfs:
        own = txns.get(mf.id, ())
        if txns_match(mf, own):
            ordered = sorted_txns(own)
            out.append(_Mf(mf, ordered, ordered[0].txn_date))
        else:
            out.append(_Mf(mf, None, mf.purchase_date))
    return out


def earliest_start(
    holdings: dict[str, Sequence[Any]], txns: dict[int, Sequence[Any]] | None = None
) -> date | None:
    """Earliest start date over every holding (MF with matching txns: its first txn)."""
    starts = [
        _holding_start(slug, r) for slug in ("fd", "rd", "stock", "bond", "gold", "cash") for r in holdings.get(slug, ())
    ]
    starts += [m.start for m in _prepare_mfs(holdings.get("mf", ()), txns or {})]
    return min(starts) if starts else None


def _mf_at(m: _Mf, d: date, navs: dict[int, Series]) -> tuple[Decimal, Decimal] | None:
    """(invested, current) of a fund on d, or None when it is not held yet."""
    if d < m.start:
        return None
    mf = m.record
    if m.txns is not None:
        units, invested = units_and_cost_at(m.txns, d)
        if units <= 0:
            return None
    else:
        units, invested = Decimal(mf.units), Decimal(mf.invested_amount)
    nav = on_or_before(navs.get(mf.scheme_code, ()), d) if mf.scheme_code is not None else None
    current = invested if nav is None else units * Decimal(nav)
    return invested, current


def build_history(
    range_key: str,
    today: date,
    holdings: dict[str, Sequence[Any]],
    navs: dict[int, Series],
    closes: dict[int, Series],
    txns: dict[int, Sequence[Any]],
    today_totals: tuple[Decimal, Decimal],
    gold_rates: dict[str, Series] | None = None,
) -> dict[str, Any]:
    """Net worth series for the range. `today_totals` = (invested, current) from the dashboard.

    `navs` {scheme_code: [(date, nav)]}, `closes` {master_id: [(date, close)]} and `gold_rates`
    {purity: [(date, rate per gram)]} are sorted by date.
    """
    gold_rates = gold_rates or {}
    start = earliest_start(holdings, txns)
    if start is None:
        return {"range": range_key, "points": [], "stocks_at_cost_before": None}
    mfs = _prepare_mfs(holdings.get("mf", ()), txns)
    points: list[dict[str, Any]] = []
    last_at_cost: int | None = None  # index of the last point with a stock valued at cost
    for d in date_list(range_key, today, start):
        invested = Decimal(0)
        current = Decimal(0)
        for slug, valuer in (
            ("fd", valuation.value_fd),
            ("rd", valuation.value_rd),
            ("bond", valuation.value_bond),
        ):
            for r in holdings.get(slug, ()):
                if _holding_start(slug, r) > d:
                    continue
                v = valuer(r, d)
                if v["status"] != "active":
                    continue
                invested += v["invested"]
                current += v["current_value"]
        for r in holdings.get("stock", ()):
            if r.buy_date > d:
                continue
            cost = Decimal(r.quantity) * Decimal(r.avg_buy_price)
            close = on_or_before(closes.get(r.master_id, ()), d) if r.master_id is not None else None
            if close is None:
                last_at_cost = len(points)
            invested += _q(cost)
            current += _q(cost) if close is None else _q(Decimal(r.quantity) * Decimal(close))
        for r in holdings.get("gold", ()):
            if r.purchase_date > d:
                continue
            cost = _q(Decimal(r.invested_amount))
            rate = on_or_before(gold_rates.get(r.purity, ()), d)
            invested += cost
            current += cost if rate is None else _q(Decimal(r.weight_grams) * Decimal(rate))
        for r in holdings.get("cash", ()):
            if r.balance_date > d:
                continue
            balance = _q(Decimal(r.balance))
            invested += balance
            current += balance
        for m in mfs:
            pair = _mf_at(m, d, navs)
            if pair is not None:
                invested += _q(pair[0])
                current += _q(pair[1])
        points.append({"date": d, "invested": _q(invested), "current": _q(current)})
    points[-1]["invested"] = _q(today_totals[0])
    points[-1]["current"] = _q(today_totals[1])
    cost_before = None
    if last_at_cost is not None:
        cost_before = points[min(last_at_cost + 1, len(points) - 1)]["date"]
    return {
        "range": range_key,
        "points": [{**p, "date": p["date"].isoformat()} for p in points],
        "stocks_at_cost_before": cost_before.isoformat() if cost_before else None,
    }
