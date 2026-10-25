"""Pure valuation helpers. Rates are percent p.a.; year fraction = days / 365."""

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from dateutil.relativedelta import relativedelta

PERIODS_PER_YEAR = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "yearly": 1}
_CENT = Decimal("0.01")


def _q(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _year_fraction(start: date, end: date) -> float:
    return max((end - start).days, 0) / 365


def _grow(amount: Decimal, rate_pct: Decimal, compounding: str, t: float) -> float:
    p = float(amount)
    r = float(rate_pct) / 100
    if compounding == "simple":
        return p * (1 + r * t)
    n = PERIODS_PER_YEAR[compounding]
    return p * (1 + r / n) ** (n * t)


def _maturity(obj: Any) -> date:
    return (
        obj.start_date
        + relativedelta(years=obj.tenure_years, months=obj.tenure_months)
        + timedelta(days=obj.tenure_days)
    )


def _result(
    invested: float | Decimal,
    current: float | Decimal,
    maturity_date: date | None = None,
    status: str = "active",
    gain: Decimal | None = None,
) -> dict[str, Any]:
    invested_d = _q(invested)
    current_d = _q(current)
    if gain is None:
        gain = current_d - invested_d
    gain_pct = _q(gain / invested_d * 100) if invested_d else Decimal("0.00")
    out: dict[str, Any] = {
        "invested": invested_d,
        "current_value": current_d,
        "gain": gain,
        "gain_pct": gain_pct,
    }
    if maturity_date is not None:
        out["maturity_date"] = maturity_date
    out["status"] = status
    return out


def _status(today: date, maturity: date) -> str:
    return "matured" if today >= maturity else "active"


def value_fd(fd: Any, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    maturity = _maturity(fd)
    if fd.payout_type == "payout":
        return _value_payout_fd(fd, today, maturity)
    t = _year_fraction(fd.start_date, min(today, maturity))
    current = _grow(fd.principal, fd.rate, fd.compounding, t)
    return _result(fd.principal, current, maturity, _status(today, maturity))


def _value_payout_fd(fd: Any, today: date, maturity: date) -> dict[str, Any]:
    periods = PERIODS_PER_YEAR[fd.compounding]
    step = 12 // periods
    principal = float(fd.principal)
    annual = principal * float(fd.rate) / 100
    end = min(today, maturity)
    completed = 0
    last_end = fd.start_date
    while True:
        period_end = fd.start_date + relativedelta(months=step * (completed + 1))
        if period_end > end:
            break
        completed += 1
        last_end = period_end
    interest = annual / periods * completed
    if today >= maturity:
        interest += annual * _year_fraction(last_end, maturity)
    received = _q(interest)
    out = _result(
        fd.principal,
        fd.principal,
        maturity,
        _status(today, maturity),
        gain=received,
    )
    out["interest_received"] = received
    return out


def value_rd(rd: Any, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    maturity = _maturity(rd)
    end = min(today, maturity)
    count = 0
    current = 0.0
    k = 0
    while True:
        d = rd.start_date + relativedelta(months=k)
        if d >= maturity or d > today:
            break
        count += 1
        current += _grow(
            rd.monthly_instalment, rd.rate, rd.compounding, _year_fraction(d, end)
        )
        k += 1
    invested = count * Decimal(rd.monthly_instalment)
    return _result(invested, current, maturity, _status(today, maturity))


def value_bond(bond: Any, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    invested = bond.quantity * Decimal(bond.purchase_price)
    t = _year_fraction(bond.purchase_date, min(today, bond.maturity_date))
    current = float(invested) * (1 + float(bond.ytm) / 100) ** t
    return _result(
        invested, current, bond.maturity_date, _status(today, bond.maturity_date)
    )


def value_stock(stock: Any, today: date | None = None) -> dict[str, Any]:
    invested = stock.quantity * Decimal(stock.avg_buy_price)
    return _result(invested, invested)


def value_mf(
    mf: Any,
    today: date | None = None,
    *,
    nav: Decimal | None = None,
    nav_date: date | None = None,
) -> dict[str, Any]:
    """Value at the latest NAV when the holding has a scheme and a NAV is known."""
    invested = Decimal(mf.units) * Decimal(mf.avg_nav)
    if mf.scheme_code is not None and nav is not None:
        out = _result(invested, Decimal(mf.units) * Decimal(nav))
        out["nav"] = Decimal(nav).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        out["nav_date"] = nav_date
        return out
    out = _result(invested, invested)
    out["nav"] = None
    out["nav_date"] = None
    return out


def aggregate(results: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Sum invested/current_value/gain over computed results; gain_pct derived."""
    invested = Decimal("0.00")
    current = Decimal("0.00")
    gain = Decimal("0.00")
    for r in results:
        invested += r["invested"]
        current += r["current_value"]
        gain += r["gain"]
    gain_pct = _q(gain / invested * 100) if invested else Decimal("0.00")
    return {
        "invested": _q(invested),
        "current_value": _q(current),
        "gain": _q(gain),
        "gain_pct": gain_pct,
    }
