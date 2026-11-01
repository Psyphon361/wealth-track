from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.assets import (
    GOLD_FORM_ERROR,
    GOLD_METAL_ERROR,
    GOLD_PURITY_ERROR,
    GOLD_WEIGHT_DECIMALS_ERROR,
    GoldCreate,
)
from app.services import valuation
from tests.conftest import make_gold
from tests.test_scoping import client, users  # noqa: F401

VALID = {
    "name": "Wedding necklace", "form": "jewellery", "metal": "gold", "purity": "916",
    "weight_grams": "25.5",
    "purchase_date": "2025-01-01", "invested_amount": "150000",
}  # fmt: skip


def _errors(**override):
    with pytest.raises(ValidationError) as exc:
        GoldCreate(**{**VALID, **override})
    return {e["loc"][0]: e["msg"] for e in exc.value.errors()}


def test_valid_gold_accepted():
    gold = GoldCreate(**VALID)
    assert gold.weight_grams == Decimal("25.5") and gold.purity == "916"


def test_required_name():
    assert _errors(name="  ") == {"name": "Required"}


def test_weight_must_be_positive():
    assert _errors(weight_grams="0") == {"weight_grams": "Must be greater than 0"}
    assert _errors(weight_grams="-1") == {"weight_grams": "Must be greater than 0"}


def test_weight_max_three_decimals():
    assert _errors(weight_grams="1.2345") == {"weight_grams": GOLD_WEIGHT_DECIMALS_ERROR}
    assert GoldCreate(**{**VALID, "weight_grams": "1.234"}).weight_grams == Decimal("1.234")


def test_amount_must_be_positive():
    assert _errors(invested_amount="0") == {"invested_amount": "Must be greater than 0"}


def test_future_date_rejected():
    future = (date.today() + timedelta(days=60)).isoformat()
    assert _errors(purchase_date=future) == {
        "purchase_date": "Date can be at most 30 days in the future"
    }


def test_bad_enums():
    assert _errors(form="ring") == {"form": GOLD_FORM_ERROR}
    assert _errors(purity="900") == {"purity": GOLD_PURITY_ERROR}


@pytest.mark.parametrize("purity", ["999", "925"])
def test_silver_accepted(purity):
    silver = GoldCreate(**{**VALID, "metal": "silver", "purity": purity})
    assert silver.metal == "silver" and silver.purity == purity


def test_silver_rejects_gold_purity():
    assert _errors(metal="silver", purity="916") == {"purity": GOLD_PURITY_ERROR}


def test_gold_rejects_925():
    assert _errors(purity="925") == {"purity": GOLD_PURITY_ERROR}


def test_metal_required_and_validated():
    assert _errors(metal="platinum") == {"metal": GOLD_METAL_ERROR}
    missing = {k: v for k, v in VALID.items() if k != "metal"}
    with pytest.raises(ValidationError) as exc:
        GoldCreate(**missing)
    # Missing fields use the shared "missing" error, same as form/purity.
    assert [(e["loc"][0], e["type"]) for e in exc.value.errors()] == [("metal", "missing")]


def test_invalid_metal_reports_only_metal_error():
    assert _errors(metal="platinum", purity="925") == {"metal": GOLD_METAL_ERROR}


def test_metal_filter_and_toasts(client, users):  # noqa: F811
    a, _, _, _ = users
    gold = client.post("/api/assets/gold", json=VALID, headers=a)
    silver_body = {**VALID, "name": "Silver coin", "metal": "silver", "purity": "999"}
    silver = client.post("/api/assets/gold", json=silver_body, headers=a)
    assert gold.json()["message"] == "Gold added"
    assert silver.status_code == 201 and silver.json()["message"] == "Silver added"

    names = lambda q: [i["name"] for i in client.get(f"/api/holdings/gold{q}", headers=a).json()["items"]]  # noqa: E731
    assert names("") and len(names("")) == 2
    assert names("?metal=silver") == ["Silver coin"]
    assert names("?metal=gold") == ["Wedding necklace"]
    assert client.get("/api/holdings/gold?sort=metal", headers=a).status_code == 200
    assert client.get("/api/holdings/gold?metal=copper", headers=a).status_code == 422

    bad = client.post("/api/assets/gold", json={**VALID, "metal": "silver"}, headers=a)
    assert bad.status_code == 422

    deleted = client.delete(f"/api/assets/gold/{silver.json()['id']}", headers=a)
    assert deleted.json()["message"] == "Silver deleted"


def test_value_with_rate():
    gold = make_gold(weight_grams=Decimal("10.5"), invested_amount=Decimal("50000"))
    out = valuation.value_gold(
        gold, date(2026, 10, 24), rate=Decimal("6000.00"), rate_date=date(2026, 10, 23)
    )
    assert out["current_value"] == Decimal("63000.00")
    assert out["gain"] == Decimal("13000.00") and out["gain_pct"] == Decimal("26.00")
    assert out["rate_per_gram"] == Decimal("6000.00") and out["rate_date"] == date(2026, 10, 23)
    assert out["status"] == "active"


def test_value_without_rate_is_invested():
    out = valuation.value_gold(make_gold(), date(2026, 10, 24))
    assert out["current_value"] == out["invested"] == Decimal("50000.00")
    assert out["gain"] == Decimal("0.00")
    assert out["rate_per_gram"] is None and out["rate_date"] is None


def test_xirr_single_cashflow():
    gold = make_gold(purchase_date=date(2025, 10, 24), invested_amount=Decimal("100000"))
    out = valuation.value_gold(
        gold, date(2026, 10, 24), rate=Decimal("12000"), rate_date=date(2026, 10, 24)
    )
    # 10 g x 12000 = 120000 after exactly 365 days: 20 %
    assert out["xirr"] == Decimal("20.00")
