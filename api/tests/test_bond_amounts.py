from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.assets import BondCreate
from app.services import valuation
from tests.conftest import make_bond

MESSAGE = "Total invested must equal quantity × purchase price"


def payload(**overrides):
    data = dict(
        name="Test Bond", isin=None, issuer="Issuer", bond_type="corporate",
        quantity=10, face_value=1000, purchase_price=990, invested_amount=9900,
        purchase_date="2025-10-24", ytm=8, maturity_date="2027-10-24",
    )  # fmt: skip
    data.update(overrides)
    return data


def errors(**overrides):
    with pytest.raises(ValidationError) as exc:
        BondCreate(**payload(**overrides))
    return [(e["loc"], e["msg"]) for e in exc.value.errors()]


def test_consistent_amounts_accepted():
    bond = BondCreate(**payload())
    assert bond.invested_amount == Decimal("9900")


def test_face_value_optional():
    data = payload()
    del data["face_value"]
    assert BondCreate(**data).face_value is None


def test_inconsistent_total_rejected():
    assert errors(invested_amount=9000) == [(("invested_amount",), MESSAGE)]


def test_rounding_tolerance():
    bond = BondCreate(**payload(quantity=3, purchase_price="333.33", invested_amount="1000.00"))
    assert bond.invested_amount == Decimal("1000.00")


def test_price_far_from_face_value_accepted():
    bond = BondCreate(**payload(face_value=1000, purchase_price=5000, invested_amount=50000))
    assert bond.purchase_price == Decimal("5000")


def test_value_bond_uses_invested_amount():
    bond = make_bond(quantity=10, purchase_price=Decimal("1000"), invested_amount=Decimal("12345.67"))
    r = valuation.value_bond(bond, date(2025, 10, 24))
    assert r["invested"] == Decimal("12345.67")
