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


def _mf(**kw):
    from types import SimpleNamespace

    fields = dict(
        units=Decimal("10"), avg_nav=Decimal("50"), scheme_code=123,
        purchase_date=date(2026, 1, 1),
    )
    fields.update(kw)
    return SimpleNamespace(**fields)


def test_mf_valued_at_latest_nav():
    r = valuation.value_mf(
        _mf(), date(2026, 10, 25), nav=Decimal("62.3456"), nav_date=date(2026, 10, 24)
    )
    assert r["invested"] == Decimal("500.00")
    assert r["current_value"] == Decimal("623.46")
    assert r["gain"] == Decimal("123.46")
    assert r["gain_pct"] == Decimal("24.69")
    assert r["nav"] == Decimal("62.3456")
    assert r["nav_date"] == date(2026, 10, 24)
    assert r["status"] == "active"


def test_mf_without_nav_falls_back_to_invested():
    r = valuation.value_mf(_mf(), date(2026, 10, 25))
    assert r["current_value"] == Decimal("500.00")
    assert r["gain"] == Decimal("0.00")
    assert r["nav"] is None and r["nav_date"] is None


def test_mf_without_scheme_code_ignores_nav():
    r = valuation.value_mf(
        _mf(scheme_code=None), date(2026, 10, 25),
        nav=Decimal("62.3456"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert r["current_value"] == Decimal("500.00")
    assert r["nav"] is None


def test_mf_xirr_one_year():
    r = valuation.value_mf(
        _mf(purchase_date=date(2025, 10, 25)), date(2026, 10, 25),
        nav=Decimal("55"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert r["xirr_pct"] == Decimal("10.00")


def test_mf_xirr_two_years():
    r = valuation.value_mf(
        _mf(purchase_date=date(2024, 10, 25)), date(2026, 10, 25),
        nav=Decimal("60.5"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert r["xirr_pct"] == Decimal("10.00")


def test_mf_xirr_short_holding_is_annualised():
    r = valuation.value_mf(
        _mf(purchase_date=date(2026, 9, 25)), date(2026, 10, 25),
        nav=Decimal("51"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    expected = Decimal(str((1.02 ** (365 / 30) - 1) * 100)).quantize(Decimal("0.01"))
    assert r["xirr_pct"] == expected


def test_mf_xirr_none_cases():
    same_day = valuation.value_mf(
        _mf(purchase_date=date(2026, 10, 25)), date(2026, 10, 25),
        nav=Decimal("55"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert same_day["xirr_pct"] is None
    zero_current = valuation.value_mf(
        _mf(purchase_date=date(2025, 10, 25)), date(2026, 10, 25),
        nav=Decimal("0"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert zero_current["xirr_pct"] is None
    zero_invested = valuation.value_mf(
        _mf(avg_nav=Decimal("0"), purchase_date=date(2025, 10, 25)), date(2026, 10, 25),
        nav=Decimal("55"), nav_date=date(2026, 10, 24),
    )  # fmt: skip
    assert zero_invested["xirr_pct"] is None
