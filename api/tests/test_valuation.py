from datetime import date
from decimal import Decimal

from app.services import valuation
from tests.conftest import make_bond, make_fd


def test_payout_fd_interest_after_maturity():
    fd = make_fd(
        principal=Decimal("100000"), rate=Decimal("8.30"), payout_type="payout",
        compounding="quarterly", start_date=date(2025, 6, 1),
        tenure_years=1, tenure_months=4, tenure_days=0,
    )  # fmt: skip
    r = valuation.value_fd(fd, date(2026, 10, 25))
    assert r["status"] == "matured"
    assert r["maturity_date"] == date(2026, 10, 1)
    assert r["invested"] == Decimal("100000.00")
    assert r["current_value"] == Decimal("100000.00")
    assert r["interest_received"] == Decimal("11057.19")
    assert r["gain"] == Decimal("11057.19")
    assert r["gain_pct"] == Decimal("11.06")


def test_cumulative_fd_quarterly_one_year():
    fd = make_fd()  # 100000 @ 7% quarterly, 2025-10-24, 1y
    r = valuation.value_fd(fd, date(2026, 10, 24))
    assert r["current_value"] == Decimal("107185.90")


def test_payout_fd_72_percent():
    fd = make_fd(rate=Decimal("7.2"), payout_type="payout", start_date=date(2025, 1, 1))
    half_year = valuation.value_fd(fd, date(2025, 7, 1))
    assert half_year["interest_received"] == Decimal("3600.00")
    at_maturity = valuation.value_fd(fd, date(2026, 1, 1))
    assert at_maturity["interest_received"] == Decimal("7200.00")


def test_bond_one_year():
    bond = make_bond()
    r = valuation.value_bond(bond, date(2026, 10, 24))
    assert r["current_value"] == Decimal("10800.00")
