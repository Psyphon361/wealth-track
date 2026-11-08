from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.assets import CASH_KIND_ERROR, CashCreate
from app.services import valuation
from tests.conftest import make_cash

VALID = {
    "name": "HDFC savings", "kind": "savings", "balance": "25000.50", "interest_rate": "3.5",
    "balance_date": "2025-10-01",
}  # fmt: skip


def _errors(**override):
    with pytest.raises(ValidationError) as exc:
        CashCreate(**{**VALID, **override})
    return {e["loc"][0]: e["msg"] for e in exc.value.errors()}


def test_valid_cash_accepted():
    cash = CashCreate(**VALID)
    assert cash.balance == Decimal("25000.50") and cash.kind == "savings"


def test_interest_rate_optional():
    data = {k: v for k, v in VALID.items() if k != "interest_rate"}
    assert CashCreate(**data).interest_rate is None


def test_required_name():
    assert _errors(name="  ") == {"name": "Required"}


def test_bad_kind():
    assert _errors(kind="wallet") == {"kind": CASH_KIND_ERROR}
    assert CASH_KIND_ERROR == "Choose an account type"


def test_balance_zero_allowed_negative_rejected():
    assert CashCreate(**{**VALID, "balance": "0"}).balance == Decimal("0")
    assert CashCreate(**{**VALID, "balance": "0.01"}).balance == Decimal("0.01")
    assert _errors(balance="-5") == {"balance": "Can't be negative"}
    assert _errors(balance="-0.01") == {"balance": "Can't be negative"}


def test_zero_balance_valuation_is_zero():
    out = valuation.value_cash(make_cash(balance=Decimal("0")), date(2026, 10, 24))
    assert out["invested"] == out["current_value"] == Decimal("0.00")
    assert out["gain"] == Decimal("0.00") and out["gain_pct"] == Decimal("0.00")


def test_rate_above_15_rejected():
    assert _errors(interest_rate="15.5") == {
        "interest_rate": "Interest rate must be between 0 and 15%"
    }


def test_future_date_rejected():
    future = (date.today() + timedelta(days=60)).isoformat()
    assert _errors(balance_date=future) == {
        "balance_date": "Date can be at most 30 days in the future"
    }


def test_value_is_balance_with_no_gain_or_xirr():
    out = valuation.value_cash(make_cash(balance=Decimal("25000")), date(2026, 10, 24))
    assert out["invested"] == out["current_value"] == Decimal("25000.00")
    assert out["gain"] == Decimal("0.00") and out["gain_pct"] == Decimal("0.00")
    assert out["xirr"] is None
    assert out["status"] == "active" and "maturity_date" not in out
