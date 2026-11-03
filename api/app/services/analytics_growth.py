"""Net worth change split into new money and growth. Pure maths over the daily net worth history
points ({date, invested, current}); no DB. See SPEC §9 "Growth"."""

from bisect import bisect_right
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Iterable

from dateutil.relativedelta import relativedelta

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT)


def month_end(year: int, month: int) -> date:
    """Last day of the given month."""
    return date(year, month, 1) + relativedelta(months=1) - timedelta(days=1)


def last_day_of_previous_month(d: date, back: int = 1) -> date:
    """Last day of the month `back` months before the month of `d`."""
    first = d.replace(day=1) - relativedelta(months=back - 1)
    return first - timedelta(days=1)


def fy_start(today: date) -> date:
    """31 March before the current Indian financial year (which starts on 1 April)."""
    return date(today.year if today.month >= 4 else today.year - 1, 3, 31)


def period_bounds(today: date) -> list[tuple[str, str, date, date]]:
    """(key, label, start_date, end_date) for the five periods, in response order."""
    last_month_end = last_day_of_previous_month(today)
    return [
        ("this_month", "This month", last_month_end, today),
        ("last_month", "Last month", last_day_of_previous_month(today, 2), last_month_end),
        ("fy", "FY to date", fy_start(today), today),
        ("ytd", "This year", date(today.year - 1, 12, 31), today),
        ("1y", "1 year", today - relativedelta(years=1), today),
    ]


class _Lookup:
    """Value and invested on or before a date, from points sorted by date."""

    def __init__(self, points: Iterable[Any]):
        rows = sorted(
            ((p["date"], Decimal(p["current"]), Decimal(p["invested"])) for p in points),
            key=lambda r: r[0],
        )
        self._dates = [r[0] for r in rows]
        self._rows = rows

    def at(self, d: date) -> tuple[Decimal, Decimal]:
        """(current, invested) of the last point on or before d; (0, 0) when there is none."""
        i = bisect_right(self._dates, d)
        if i == 0:
            return ZERO, ZERO
        _, current, invested = self._rows[i - 1]
        return current, invested


def _split(lookup: _Lookup, start: date, end: date) -> dict[str, Decimal]:
    start_value, start_invested = lookup.at(start)
    end_value, end_invested = lookup.at(end)
    new_money = end_invested - start_invested
    change = end_value - start_value
    return {
        "start_value": start_value,
        "end_value": end_value,
        "new_money": new_money,
        "growth": change - new_money,
        "change": change,
    }


def _rounded(parts: dict[str, Decimal]) -> dict[str, Decimal]:
    out = {k: _money(v) for k, v in parts.items()}
    # Keep the rounded figures adding up: growth is what remains of the rounded change.
    out["growth"] = out["change"] - out["new_money"]
    return out


def build_growth(
    points: list[Any], today: date, stocks_at_cost_before: date | None = None
) -> dict[str, Any]:
    lookup = _Lookup(points)

    periods = []
    for key, label, start, end in period_bounds(today):
        parts = _split(lookup, start, end)
        growth_pct = (
            _money(parts["growth"] * 100 / parts["start_value"]) if parts["start_value"] else None
        )
        periods.append(
            {
                "key": key,
                "label": label,
                "start_date": start,
                "end_date": end,
                **_rounded(parts),
                "growth_pct": growth_pct,
            }
        )

    months = []
    for back in range(11, -1, -1):
        first = today.replace(day=1) - relativedelta(months=back)
        end = today if back == 0 else month_end(first.year, first.month)
        start = first - timedelta(days=1)
        months.append({"month": f"{first.year:04d}-{first.month:02d}", **_rounded(_split(lookup, start, end))})

    return {
        "as_of": today,
        "stocks_at_cost_before": stocks_at_cost_before,
        "periods": periods,
        "months": months,
    }
