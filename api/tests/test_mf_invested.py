from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.assets import MutualFundCreate
from app.services import valuation

MESSAGE = "Total invested must equal units × average NAV"


def payload(**overrides):
    data = dict(
        scheme_name="Test Fund", category="equity", units="5385.280", avg_nav="47.8100",
        invested_amount="257470.24", purchase_date="2025-01-01",
    )  # fmt: skip
    data.update(overrides)
    return data


def errors(**overrides):
    with pytest.raises(ValidationError) as exc:
        MutualFundCreate(**payload(**overrides))
    return [(e["loc"], e["msg"]) for e in exc.value.errors()]


def test_rounded_total_accepted():
    mf = MutualFundCreate(**payload())
    assert mf.invested_amount == Decimal("257470.24")


def test_exact_total_accepted():
    mf = MutualFundCreate(**payload(units="10", avg_nav="50", invested_amount="500"))
    assert mf.invested_amount == Decimal("500")


def test_wrong_total_rejected():
    assert errors(invested_amount="200000") == [(("invested_amount",), MESSAGE)]


def test_missing_total_rejected():
    data = payload()
    del data["invested_amount"]
    with pytest.raises(ValidationError) as exc:
        MutualFundCreate(**data)
    assert [e["loc"] for e in exc.value.errors()] == [("invested_amount",)]


def test_value_mf_uses_stored_invested():
    mf = SimpleNamespace(
        units=Decimal("10"), avg_nav=Decimal("50"), invested_amount=Decimal("500.40"),
        scheme_code=None, purchase_date=date(2026, 1, 1),
    )  # fmt: skip
    assert valuation.value_mf(mf, date(2026, 10, 25))["invested"] == Decimal("500.40")
