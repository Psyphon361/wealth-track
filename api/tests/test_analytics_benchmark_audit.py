"""Audit tests for the Returns benchmark (replay, fd_rate, inflation, CPI file) and the
concentration `others` block. Expected values are computed by hand, not through the code."""

import random
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import analytics
from app.services import analytics_benchmark as ab
from app.services import valuation
from app.services.valuation import xirr

D = Decimal
TODAY = date(2026, 11, 3)


# --- replay ------------------------------------------------------------------------------------


def test_constant_nav_gives_zero_benchmark_annualised_and_absolute():
    rows = [(date(2024, 1, 1), D(10)), (TODAY, D(10))]
    pct, annualised = ab.replay([(date(2025, 1, 1), D(-1000)), (TODAY, D(1500))], rows, TODAY)
    assert annualised is True and abs(pct) <= D("0.01")
    pct, annualised = ab.replay([(date(2026, 6, 1), D(-1000)), (TODAY, D(1500))], rows, TODAY)
    assert annualised is False and pct == D("0.00")


def test_nav_doubling_over_730_days_is_41_42_percent_a_year():
    start = TODAY - timedelta(days=730)
    rows = [(start, D(10)), (TODAY, D(20))]
    pct, annualised = ab.replay([(start, D(-1000)), (TODAY, D(5000))], rows, TODAY)
    assert annualised is True
    assert float(pct) == pytest.approx((2 ** (365 / 730) - 1) * 100, abs=0.01)  # 41.42


def test_flows_that_are_the_index_fund_match_your_return():
    start = date(2025, 3, 3)
    rows = [(start, D(10)), (date(2025, 9, 1), D(13)), (TODAY, D(15))]
    buys = [(start, D(-1000)), (date(2025, 9, 1), D(-2600))]
    units = D(1000) / 10 + D(2600) / 13
    flows = [*buys, (TODAY, units * 15)]
    own = xirr(flows)
    pct, annualised = ab.replay(flows, rows, TODAY)
    assert annualised is True
    assert pct == (own * 100).quantize(D("0.01"))
    # absolute path
    start = date(2026, 5, 1)
    rows = [(start, D(10)), (TODAY, D(12))]
    flows = [(start, D(-1000)), (TODAY, D(1200))]
    pct, annualised = ab.replay(flows, rows, TODAY)
    assert (pct, annualised) == (D("20.00"), False)


def test_buys_and_a_redemption_by_hand():
    rows = [(date(2026, 6, 1), D(10)), (date(2026, 8, 1), D(20)), (TODAY, D(25))]
    flows = [
        (date(2026, 6, 1), D(-1000)),  # 100 units
        (date(2026, 8, 1), D(-1000)),  # 50 units
        (date(2026, 9, 15), D(500)),  # NAV on or before = 20 -> sells 25 units
        (TODAY, D(9999)),  # replaced by 125 units x 25 = 3125
    ]
    # (3125 + 500 - 2000) / 2000
    assert ab.replay(flows, rows, TODAY) == (D("81.25"), False)


def test_flow_on_non_nav_day_uses_prior_nav():
    rows = [(date(2026, 6, 1), D(10)), (date(2026, 6, 5), D(12)), (TODAY, D(10))]
    pct, _ = ab.replay([(date(2026, 6, 4), D(-1000)), (TODAY, D(1))], rows, TODAY)
    assert pct == D("0.00")  # bought at 10, worth 10


def test_flow_before_first_nav_is_none():
    rows = [(date(2025, 1, 1), D(10)), (TODAY, D(11))]
    assert ab.replay([(date(2024, 12, 31), D(-1000)), (TODAY, D(1200))], rows, TODAY) == (None, True)
    assert ab.replay([(date(2026, 1, 1), D(-1000)), (TODAY, D(1))], [], TODAY) == (None, False)


def test_positive_flow_dated_today_is_terminal_whatever_its_size():
    rows = [(date(2026, 6, 1), D(10)), (TODAY, D(12))]
    small = ab.replay([(date(2026, 6, 1), D(-1000)), (TODAY, D(1))], rows, TODAY)
    big = ab.replay([(date(2026, 6, 1), D(-1000)), (TODAY, D(10**6))], rows, TODAY)
    assert small == big == (D("20.00"), False)
    # a same-day redemption is indistinguishable from the holding's current value: replaying it
    # as a sale at today's NAV or keeping the units gives the same answer.
    two = ab.replay(
        [(date(2026, 6, 1), D(-1000)), (TODAY, D(600)), (TODAY, D(600))], rows, TODAY
    )
    assert two == (D("20.00"), False)


def test_same_day_buy_is_not_dropped():
    rows = [(date(2026, 6, 1), D(10)), (TODAY, D(12))]
    pct, _ = ab.replay([(TODAY, D(-1000)), (TODAY, D(1000))], rows, TODAY)
    assert pct == D("0.00")


# --- fd_rate -----------------------------------------------------------------------------------


def _real_fd_item(id_, principal, rate, start, years=1):
    fd = SimpleNamespace(
        principal=D(principal), rate=D(rate), compounding="quarterly", payout_type="cumulative",
        start_date=start, tenure_years=years, tenure_months=0, tenure_days=0,
    )  # fmt: skip
    computed = valuation.value_fd(fd, TODAY)
    # portfolio._item merges the FD read schema (principal, rate) with the computed values
    item = {"id": id_, "principal": float(principal), "rate": float(rate)}
    item.update({k: float(v) if isinstance(v, D) else v for k, v in computed.items()})
    return item


def test_fd_rate_with_real_item_shapes_weighted_and_matured_excluded():
    items = [
        _real_fd_item(1, 100000, "7", date(2026, 1, 1)),
        _real_fd_item(2, 300000, "8", date(2026, 3, 1)),
        _real_fd_item(3, 900000, "3", date(2024, 1, 1)),  # matured
    ]
    assert [i["status"] for i in items] == ["active", "active", "matured"]
    assert ab.fd_rate([{"type": "fd", "items": items}]) == D("7.75")


def test_fd_rate_zero_principal_and_other_types():
    assert ab.fd_rate([{"type": "fd", "items": [
        {"status": "active", "principal": 0, "rate": 7}]}]) is None
    assert ab.fd_rate([{"type": "rd", "items": [
        {"status": "active", "principal": 100, "rate": 7}]}]) is None


# --- inflation ---------------------------------------------------------------------------------

CPI = {2021: D("5.0"), 2022: D("6.0"), 2023: D("4.0"), 2024: D("2.0")}


def test_inflation_compounding_by_hand():
    # one year: only the last year
    assert ab.inflation(date(2024, 5, 1), CPI) == (D("2.00"), "2024")
    # three years 2022-2024: (1.06*1.04*1.02)^(1/3)-1 = 3.9967...%
    g = 1.06 * 1.04 * 1.02
    pct, label = ab.inflation(date(2022, 1, 1), CPI)
    assert label == "2022–2024"
    assert float(pct) == pytest.approx((g ** (1 / 3) - 1) * 100, abs=0.005)
    # all years
    g4 = 1.05 * g
    pct, label = ab.inflation(date(2021, 1, 1), CPI)
    assert label == "2021–2024"
    assert float(pct) == pytest.approx((g4 ** 0.25 - 1) * 100, abs=0.005)


def test_inflation_clips_early_since_and_nulls_later_since():
    assert ab.inflation(date(1990, 1, 1), CPI) == ab.inflation(date(2021, 12, 31), CPI)
    assert ab.inflation(date(2025, 1, 1), CPI) == (None, None)
    assert ab.inflation(None, CPI) == (None, None)


def test_cpi_file_has_every_year_from_2013():
    cpi = ab.load_cpi()
    assert min(cpi) == 2013
    assert set(range(2013, max(cpi) + 1)) == set(cpi)
    assert all(D(0) < v < D(20) for v in cpi.values())
    assert max(cpi) >= TODAY.year - 1


# --- concentration others ----------------------------------------------------------------------


def _portfolio(values, type_="stock"):
    items = [
        {"id": i + 1, "name": f"H{i + 1}", "status": "active", "current_value": v,
         "invested": v, "master_id": None, "symbol": f"H{i + 1}"}
        for i, v in enumerate(values)
    ]  # fmt: skip
    return [{"type": type_, "label": "Stocks", "items": items}]


@pytest.mark.parametrize("n", [0, 1, 10, 11, 25])
def test_others_reconciles_with_total(n):
    rng = random.Random(n)
    values = [D(rng.randrange(100, 10**6)) / 3 for _ in range(n)]
    values = [v.quantize(D("0.01")) for v in values]
    result = analytics.concentration(_portfolio(values))
    top, others = result["top_holdings"], result["others"]
    assert len(top) == min(n, 10)
    assert others["count"] == max(0, n - 10)
    assert abs(sum(t["value"] for t in top) + others["value"] - result["total"]) <= D("0.01")
    if n:
        assert abs(sum(t["percent"] for t in top) + others["percent"] - 100) <= D("0.07")
    else:
        assert others == {"count": 0, "value": D("0.00"), "percent": D("0.00")}
    if n <= 10:
        assert others["value"] == D("0.00") and others["percent"] == D("0.00")


def test_others_ties_at_the_tenth_position_are_deterministic():
    values = [D(500)] * 3 + [D(100)] * 10  # 10th and beyond all tie at 100
    base = _portfolio(values)
    first = analytics.concentration(base)
    shuffled_items = list(base[0]["items"])
    random.Random(1).shuffle(shuffled_items)
    second = analytics.concentration([{**base[0], "items": shuffled_items}])
    assert [t["id"] for t in first["top_holdings"]] == [t["id"] for t in second["top_holdings"]]
    assert first["others"] == second["others"]
    assert first["others"]["count"] == 3 and first["others"]["value"] == D("300.00")
