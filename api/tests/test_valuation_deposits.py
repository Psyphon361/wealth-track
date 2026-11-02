"""FD, RD and bond valuation with hand-worked expected values.

All date spans stay within 2025-2027 and avoid 29 Feb on purpose.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import valuation
from tests.conftest import make_bond, make_fd

D = Decimal


def make_rd(**kw):
    fields = dict(
        bank="Test Bank", monthly_instalment=D("10000"), rate=D("12"),
        start_date=date(2025, 1, 1), compounding="quarterly",
        tenure_years=0, tenure_months=6, tenure_days=0,
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(**fields)


# ---- cumulative FD: 100000 @ 8% from 2025-01-01 for 1 year (365 days, t = 1) ----


@pytest.mark.parametrize(
    ("compounding", "at_maturity", "day_before"),
    [
        ("monthly", "108299.95", "108276.30"),
        ("quarterly", "108243.22", "108219.73"),
        ("half_yearly", "108160.00", "108136.76"),
        ("yearly", "108000.00", "107977.23"),
        ("simple", "108000.00", "107978.08"),
    ],
)
def test_cumulative_fd_compounding(compounding, at_maturity, day_before):
    fd = make_fd(rate=D("8"), start_date=date(2025, 1, 1), compounding=compounding)
    on = valuation.value_fd(fd, date(2026, 1, 1))
    assert on["maturity_date"] == date(2026, 1, 1)
    assert on["status"] == "matured"
    assert on["invested"] == D("100000.00")
    assert on["current_value"] == D(at_maturity)
    assert on["gain"] == D(at_maturity) - D("100000.00")

    before = valuation.value_fd(fd, date(2025, 12, 31))
    assert before["status"] == "active"
    assert before["current_value"] == D(day_before)


def test_cumulative_fd_gain_pct():
    fd = make_fd(rate=D("8"), start_date=date(2025, 1, 1), compounding="half_yearly")
    r = valuation.value_fd(fd, date(2026, 1, 1))
    assert r["gain"] == D("8160.00")
    assert r["gain_pct"] == D("8.16")


def test_cumulative_fd_value_flat_after_maturity():
    fd = make_fd(rate=D("8"), start_date=date(2025, 1, 1), compounding="quarterly")
    r = valuation.value_fd(fd, date(2027, 6, 1))
    assert r["status"] == "matured"
    assert r["current_value"] == D("108243.22")
    assert r["gain"] == D("8243.22")


def test_cumulative_fd_simple_two_years():
    fd = make_fd(rate=D("8"), start_date=date(2025, 1, 1), compounding="simple", tenure_years=2)
    r = valuation.value_fd(fd, date(2027, 1, 1))
    assert r["maturity_date"] == date(2027, 1, 1)
    assert r["current_value"] == D("116000.00")
    assert r["gain_pct"] == D("16.00")


def test_cumulative_fd_before_start_equals_principal():
    fd = make_fd(rate=D("8"), start_date=date(2025, 6, 1), compounding="monthly")
    r = valuation.value_fd(fd, date(2025, 5, 1))
    assert r["status"] == "active"
    assert r["invested"] == D("100000.00")
    assert r["current_value"] == D("100000.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")


def test_cumulative_fd_tenure_years_months_days():
    fd = make_fd(
        rate=D("8"), start_date=date(2025, 1, 1), compounding="yearly",
        tenure_years=1, tenure_months=2, tenure_days=10,
    )  # fmt: skip
    # 2025-01-01 + 1y 2m = 2026-03-01, + 10 days = 2026-03-11 (434 days from start)
    r = valuation.value_fd(fd, date(2026, 3, 11))
    assert r["maturity_date"] == date(2026, 3, 11)
    assert r["status"] == "matured"
    assert r["current_value"] == D("109582.76")
    assert valuation.value_fd(fd, date(2026, 3, 10))["status"] == "active"


# ---- payout FD: 100000 @ 12% (12000 a year) from 2025-01-01 ----


@pytest.mark.parametrize(
    ("compounding", "today", "expected"),
    [
        ("monthly", date(2025, 3, 15), "2000.00"),
        ("quarterly", date(2025, 7, 15), "6000.00"),
        ("half_yearly", date(2025, 7, 1), "6000.00"),
        ("yearly", date(2026, 1, 1), "12000.00"),
    ],
)
def test_payout_fd_interest_by_frequency(compounding, today, expected):
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding=compounding,
        start_date=date(2025, 1, 1), tenure_years=2,
    )  # fmt: skip
    r = valuation.value_fd(fd, today)
    assert r["status"] == "active"
    assert r["interest_received"] == D(expected)
    assert r["gain"] == D(expected)


@pytest.mark.parametrize(
    ("compounding", "last_day_before_first_payout"),
    [
        ("monthly", date(2025, 1, 31)),
        ("quarterly", date(2025, 3, 31)),
        ("half_yearly", date(2025, 6, 30)),
        ("yearly", date(2025, 12, 31)),
    ],
)
def test_payout_fd_no_interest_before_first_period_ends(compounding, last_day_before_first_payout):
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding=compounding,
        start_date=date(2025, 1, 1), tenure_years=2,
    )  # fmt: skip
    r = valuation.value_fd(fd, last_day_before_first_payout)
    assert r["interest_received"] == D("0.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")


def test_payout_fd_current_is_principal_and_gain_is_interest():
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding="quarterly",
        start_date=date(2025, 1, 1), tenure_years=1,
    )  # fmt: skip
    r = valuation.value_fd(fd, date(2025, 10, 1))  # three quarters paid
    assert r["invested"] == D("100000.00")
    assert r["current_value"] == D("100000.00")
    assert r["interest_received"] == D("9000.00")
    assert r["gain"] == r["interest_received"]
    assert r["gain_pct"] == D("9.00")


def test_payout_fd_whole_periods_on_maturity_day():
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding="monthly",
        start_date=date(2025, 1, 1), tenure_years=1,
    )  # fmt: skip
    r = valuation.value_fd(fd, date(2026, 1, 1))
    assert r["status"] == "matured"
    assert r["maturity_date"] == date(2026, 1, 1)
    assert r["interest_received"] == D("12000.00")
    assert r["gain_pct"] == D("12.00")
    # the day before: 11 payouts only
    assert valuation.value_fd(fd, date(2025, 12, 31))["interest_received"] == D("11000.00")


def test_payout_fd_stub_interest_counted_only_when_matured():
    # quarterly payout, 5 month tenure: matures 2025-06-01; one full quarter (to 1 Apr),
    # then a 61-day stub (1 Apr to 1 Jun) paid at maturity: 12000 * 61 / 365 = 2005.48
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding="quarterly",
        start_date=date(2025, 1, 1), tenure_years=0, tenure_months=5,
    )  # fmt: skip
    before = valuation.value_fd(fd, date(2025, 5, 31))
    assert before["status"] == "active"
    assert before["interest_received"] == D("3000.00")
    on = valuation.value_fd(fd, date(2025, 6, 1))
    assert on["status"] == "matured"
    assert on["interest_received"] == D("5005.48")
    assert on["gain_pct"] == D("5.01")
    after = valuation.value_fd(fd, date(2026, 6, 1))
    assert after["interest_received"] == D("5005.48")


def test_payout_fd_yearly_with_stub_after_maturity():
    # 1y 6m tenure, yearly payout: 12000 at 2026-01-01, then 181-day stub: 12000 * 181 / 365 = 5950.68
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding="yearly",
        start_date=date(2025, 1, 1), tenure_years=1, tenure_months=6,
    )  # fmt: skip
    r = valuation.value_fd(fd, date(2026, 7, 1))
    assert r["maturity_date"] == date(2026, 7, 1)
    assert r["interest_received"] == D("17950.68")


def test_payout_fd_month_end_start_clamps_to_short_months():
    # Payout dates are start + n months: 28 Feb, 31 Mar, 30 Apr, 31 May.
    fd = make_fd(
        rate=D("12"), payout_type="payout", compounding="monthly",
        start_date=date(2025, 1, 31), tenure_years=0, tenure_months=4,
    )  # fmt: skip
    assert valuation.value_fd(fd, date(2025, 2, 27))["interest_received"] == D("0.00")
    assert valuation.value_fd(fd, date(2025, 2, 28))["interest_received"] == D("1000.00")
    assert valuation.value_fd(fd, date(2025, 3, 30))["interest_received"] == D("1000.00")
    assert valuation.value_fd(fd, date(2025, 3, 31))["interest_received"] == D("2000.00")
    assert valuation.value_fd(fd, date(2025, 4, 30))["interest_received"] == D("3000.00")
    on = valuation.value_fd(fd, date(2025, 5, 31))
    assert on["maturity_date"] == date(2025, 5, 31)
    assert on["status"] == "matured"
    assert on["interest_received"] == D("4000.00")


# ---- RD: 10000 a month @ 12% quarterly from 2025-01-01 ----


@pytest.mark.parametrize(
    ("today", "count", "status"),
    [
        (date(2025, 1, 1), 1, "active"),  # first instalment falls on today
        (date(2025, 2, 28), 2, "active"),
        (date(2025, 3, 1), 3, "active"),  # instalment exactly on today counts
        (date(2025, 6, 30), 6, "active"),
        (date(2025, 7, 1), 6, "matured"),  # 1 Jul is the maturity date: no instalment
        (date(2026, 7, 1), 6, "matured"),
    ],
)
def test_rd_instalment_count(today, count, status):
    r = valuation.value_rd(make_rd(), today)
    assert r["maturity_date"] == date(2025, 7, 1)
    assert r["status"] == status
    assert r["invested"] == D(count * 10000).quantize(D("0.01"))


def test_rd_before_start_is_zero():
    r = valuation.value_rd(make_rd(start_date=date(2025, 6, 1)), date(2025, 5, 1))
    assert r["status"] == "active"
    assert r["invested"] == D("0.00")
    assert r["current_value"] == D("0.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")


def test_rd_simple_three_instalments_at_maturity():
    # Instalments 1 Jan, 1 Feb, 1 Mar held 90, 59, 31 days to 1 Apr:
    # 30000 + 10000 * 0.12 * (90 + 59 + 31) / 365 = 30000 + 591.78
    rd = make_rd(compounding="simple", tenure_months=3)
    r = valuation.value_rd(rd, date(2025, 4, 1))
    assert r["maturity_date"] == date(2025, 4, 1)
    assert r["status"] == "matured"
    assert r["invested"] == D("30000.00")
    assert r["current_value"] == D("30591.78")
    assert r["gain"] == D("591.78")
    assert r["gain_pct"] == D("1.97")


def test_rd_quarterly_three_instalments_at_maturity():
    # sum of 10000 * 1.03 ^ (4 * days / 365) for days = 90, 59, 31
    rd = make_rd(compounding="quarterly", tenure_months=3)
    r = valuation.value_rd(rd, date(2025, 4, 1))
    assert r["invested"] == D("30000.00")
    assert r["current_value"] == D("30589.71")
    assert r["gain"] == D("589.71")
    assert r["gain_pct"] == D("1.97")


def test_rd_value_flat_after_maturity():
    rd = make_rd(compounding="quarterly", tenure_months=3)
    on = valuation.value_rd(rd, date(2025, 4, 1))
    later = valuation.value_rd(rd, date(2026, 12, 1))
    assert later["status"] == "matured"
    assert later["current_value"] == on["current_value"] == D("30589.71")


def test_rd_simple_mid_term():
    # Today 2025-03-15 with tenure 6 months: instalments 1 Jan, 1 Feb, 1 Mar held 73, 42, 14 days.
    # 30000 + 10000 * 0.12 * 129 / 365 = 30000 + 424.11
    rd = make_rd(compounding="simple")
    r = valuation.value_rd(rd, date(2025, 3, 15))
    assert r["status"] == "active"
    assert r["invested"] == D("30000.00")
    assert r["current_value"] == D("30424.11")
    assert r["gain_pct"] == D("1.41")


def test_rd_quarterly_mid_term():
    # sum of 10000 * 1.03 ^ (4 * days / 365) for days = 73, 42, 14
    r = valuation.value_rd(make_rd(compounding="quarterly"), date(2025, 3, 15))
    assert r["invested"] == D("30000.00")
    assert r["current_value"] == D("30421.72")


def test_rd_full_term_six_months_quarterly():
    # 6% quarterly: sum of 10000 * 1.015 ^ (4 * days / 365) for days = 181, 150, 122, 91, 61, 30
    r = valuation.value_rd(make_rd(rate=D("6")), date(2025, 7, 1))
    assert r["status"] == "matured"
    assert r["invested"] == D("60000.00")
    assert r["current_value"] == D("61047.23")
    assert r["gain"] == D("1047.23")
    assert r["gain_pct"] == D("1.75")


# ---- bond: 10000 @ 8% ytm, 2025-01-01 to 2027-01-01 ----


def _bond(**kw):
    fields = dict(
        invested_amount=D("10000"), ytm=D("8"),
        purchase_date=date(2025, 1, 1), maturity_date=date(2027, 1, 1),
    )  # fmt: skip
    fields.update(kw)
    return make_bond(**fields)


def test_bond_partial_year_accrual():
    # 181 days: 10000 * 1.08 ^ (181 / 365)
    r = valuation.value_bond(_bond(), date(2025, 7, 1))
    assert r["status"] == "active"
    assert r["invested"] == D("10000.00")
    assert r["current_value"] == D("10389.02")
    assert r["gain"] == D("389.02")
    assert r["gain_pct"] == D("3.89")


def test_bond_on_maturity_date():
    r = valuation.value_bond(_bond(), date(2027, 1, 1))
    assert r["status"] == "matured"
    assert r["maturity_date"] == date(2027, 1, 1)
    assert r["current_value"] == D("11664.00")


def test_bond_value_clamps_at_maturity():
    r = valuation.value_bond(_bond(), date(2027, 6, 1))
    assert r["status"] == "matured"
    assert r["current_value"] == D("11664.00")
    assert r["gain"] == D("1664.00")
    assert r["gain_pct"] == D("16.64")


def test_bond_purchase_date_after_today():
    bond = _bond(purchase_date=date(2026, 6, 1), maturity_date=date(2027, 6, 1))
    r = valuation.value_bond(bond, date(2026, 3, 1))
    assert r["status"] == "active"
    assert r["invested"] == D("10000.00")
    assert r["current_value"] == D("10000.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")


def test_bond_zero_ytm_stays_at_invested():
    r = valuation.value_bond(_bond(ytm=D("0")), date(2026, 3, 1))
    assert r["current_value"] == D("10000.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")


# ---- _result ----


def test_result_zero_invested_gain_pct_zero():
    r = valuation._result(0, 0)
    assert r["invested"] == D("0.00")
    assert r["gain"] == D("0.00")
    assert r["gain_pct"] == D("0.00")
    # a value with nothing invested still reports the gain, but no percentage
    r = valuation._result(D("0"), D("250"))
    assert r["gain"] == D("250.00")
    assert r["gain_pct"] == D("0.00")


def test_result_rounds_half_up_not_bankers():
    # 100.125 -> 100.13 (bankers' rounding would give 100.12)
    r = valuation._result(D("100"), D("100.125"))
    assert r["current_value"] == D("100.13")
    assert r["gain"] == D("0.13")
    # 1.005 -> 1.01 (bankers' would give 1.00)
    assert valuation._result(D("1.005"), D("2"))["invested"] == D("1.01")
    # gain_pct = 0.01 / 8.00 * 100 = 0.125 -> 0.13 (bankers' would give 0.12)
    assert valuation._result(D("8.00"), D("8.01"))["gain_pct"] == D("0.13")
