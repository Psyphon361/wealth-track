from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.routers.assets import ASSET_LABELS, REGISTRY
from app.routers.deleted import deleted_union
from app.routers.master import distinct_categories
from app.routers.portfolio import LABELS
from app.schemas.assets import OTHER_ACQUIRED_AFTER_VALUE_ERROR, OtherCreate
from app.services import networth, valuation
from app.services.purge import HOLDING_MODELS
from tests.conftest import make_other
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

VALID = {
    "name": "Bitcoin", "category": "Crypto", "current_value": "80000", "value_date": "2025-10-01",
}  # fmt: skip
TODAY = date(2026, 10, 31)


def _errors(**override):
    with pytest.raises(ValidationError) as exc:
        OtherCreate(**{**VALID, **override})
    return {e["loc"][0]: e["msg"] for e in exc.value.errors()}


def test_valid_other_accepted_and_optionals_default_to_none():
    other = OtherCreate(**VALID)
    assert other.current_value == Decimal("80000") and other.category == "Crypto"
    assert other.invested_amount is None and other.acquired_on is None


def test_required_fields():
    for field in ("name", "category", "current_value", "value_date"):
        data = {k: v for k, v in VALID.items() if k != field}
        with pytest.raises(ValidationError):
            OtherCreate(**data)
    assert _errors(name="  ") == {"name": "Required"}
    assert _errors(category="  ") == {"category": "Required"}


def test_category_is_trimmed_and_limited_to_40_chars():
    assert OtherCreate(**{**VALID, "category": "  Crypto  "}).category == "Crypto"
    assert OtherCreate(**{**VALID, "category": "x" * 40}).category == "x" * 40
    assert _errors(category="x" * 41) == {"category": "Must be at most 40 characters"}


def test_amounts_must_be_positive():
    assert _errors(current_value="0") == {"current_value": "Must be greater than 0"}
    assert _errors(invested_amount="-5") == {"invested_amount": "Must be greater than 0"}
    assert _errors(invested_amount="0") == {"invested_amount": "Must be greater than 0"}


def test_dates_cannot_be_in_the_future():
    message = "Date can be at most 30 days in the future"
    assert _errors(value_date="2099-01-01") == {"value_date": message}
    assert _errors(acquired_on="2099-01-01") == {"acquired_on": message}


def test_acquired_after_value_date_is_a_field_error():
    assert OTHER_ACQUIRED_AFTER_VALUE_ERROR == "Purchase date can't be after the value date"
    assert _errors(acquired_on="2025-10-02") == {"acquired_on": OTHER_ACQUIRED_AFTER_VALUE_ERROR}
    assert OtherCreate(**{**VALID, "acquired_on": "2025-10-01"}).acquired_on == date(2025, 10, 1)


def test_value_other_without_invested_has_no_gain():
    out = valuation.value_other(make_other(current_value=Decimal("80000")), TODAY)
    assert out["current_value"] == Decimal("80000.00") and out["invested"] == Decimal("80000.00")
    assert out["gain"] is None and out["gain_pct"] is None
    assert out["xirr"] is None and out["status"] == "active"


def test_value_other_with_invested_has_gain():
    out = valuation.value_other(
        make_other(current_value=Decimal("90000"), invested_amount=Decimal("60000")), TODAY
    )
    assert out["invested"] == Decimal("60000.00") and out["current_value"] == Decimal("90000.00")
    assert out["gain"] == Decimal("30000.00") and out["gain_pct"] == Decimal("50.00")


def test_aggregate_ignores_missing_gain():
    results = [
        valuation.value_other(make_other(current_value=Decimal("100")), TODAY),
        valuation.value_other(
            make_other(current_value=Decimal("150"), invested_amount=Decimal("100")), TODAY
        ),
    ]
    totals = valuation.aggregate(results)
    assert totals["current_value"] == Decimal("250.00") and totals["gain"] == Decimal("50.00")


def _history(other):
    return networth.build_history(
        "1m", TODAY, {"other": [other]}, {}, {}, {}, (Decimal("0"), Decimal("0"))
    )


def _point(result, day):
    return next(p for p in result["points"] if p["date"] == day)


def test_networth_starts_at_value_date_without_acquired_on():
    result = _history(make_other(value_date=date(2026, 10, 10), current_value=Decimal("5000")))
    assert _point(result, "2026-10-09")["current"] == Decimal("0.00")
    p = _point(result, "2026-10-10")
    assert p["invested"] == Decimal("5000.00") and p["current"] == Decimal("5000.00")


def test_networth_acquired_on_without_invested_is_ignored():
    other = make_other(value_date=date(2026, 10, 10), acquired_on=date(2026, 10, 3))
    assert networth._holding_start("other", other) == date(2026, 10, 10)
    assert _point(_history(other), "2026-10-05")["current"] == Decimal("0.00")


def test_networth_counts_at_cost_from_acquired_on_then_at_value():
    other = make_other(
        acquired_on=date(2026, 10, 3), value_date=date(2026, 10, 12),
        invested_amount=Decimal("60000"), current_value=Decimal("90000"),
    )  # fmt: skip
    assert networth._holding_start("other", other) == date(2026, 10, 3)
    result = _history(other)
    assert _point(result, "2026-10-02")["invested"] == Decimal("0.00")
    for day in ("2026-10-03", "2026-10-11"):
        p = _point(result, day)
        assert p["invested"] == Decimal("60000.00") and p["current"] == Decimal("60000.00")
    p = _point(result, "2026-10-12")
    assert p["invested"] == Decimal("60000.00") and p["current"] == Decimal("90000.00")


def test_networth_invested_without_acquired_on_uses_invested_from_value_date():
    other = make_other(
        value_date=date(2026, 10, 12), invested_amount=Decimal("60000"),
        current_value=Decimal("90000"),
    )  # fmt: skip
    result = _history(other)
    assert _point(result, "2026-10-11")["current"] == Decimal("0.00")
    p = _point(result, "2026-10-12")
    assert p["invested"] == Decimal("60000.00") and p["current"] == Decimal("90000.00")


def test_networth_earliest_start_includes_other():
    other = make_other(value_date=date(2026, 3, 1))
    assert networth.earliest_start({"other": [other]}) == date(2026, 3, 1)


def test_other_is_in_every_registry():
    from app.models import Other

    assert REGISTRY["other"][0] is Other
    assert ASSET_LABELS["other"] == "Other" and LABELS["other"] == "Other"
    assert HOLDING_MODELS["other"] is Other
    assert set(HOLDING_MODELS) == set(REGISTRY)
    sql = str(deleted_union(1, datetime.now(timezone.utc)).compile())
    assert "other_holdings" in sql


def test_categories_distinct_case_insensitive_newest_spelling_most_used_first():
    rows = [("Crypto", 1), ("art", 2), ("crypto", 3), ("Art", 4), ("Watches", 5), ("CRYPTO", 6)]
    assert distinct_categories(rows) == ["CRYPTO", "Art", "Watches"]


def test_categories_capped_at_20():
    rows = [(f"cat{i}", i) for i in range(30)]
    assert len(distinct_categories(rows)) == 20


def test_crud_toasts_grid_categories_and_scoping(client, users):  # noqa: F811
    a, _, b, _ = users
    created = client.post("/api/assets/other", json=VALID, headers=a)
    assert created.status_code == 201
    body = created.json()
    assert body["message"] == "Other added" and body["description"] == "Bitcoin"
    client.post("/api/assets/other", json={**VALID, "name": "Ether", "category": "crypto"}, headers=a)
    client.post(
        "/api/assets/other",
        json={**VALID, "name": "Painting", "category": "Art", "invested_amount": "50000"},
        headers=a,
    )

    grid = client.get("/api/holdings/other", headers=a).json()
    assert grid["total"] == 3
    assert grid["facets"]["category"] == [
        {"value": "crypto", "count": 2}, {"value": "Art", "count": 1}
    ]
    assert {i["category"] for i in grid["items"]} == {"crypto", "Art"}
    assert client.get("/api/holdings/other?q=pain", headers=a).json()["total"] == 1
    assert client.get("/api/holdings/other?q=ART", headers=a).json()["total"] == 1
    assert client.get("/api/holdings/other?category=crypto", headers=a).json()["total"] == 2
    for sort in ("name", "category", "current_value", "invested", "gain", "value_date"):
        assert client.get(f"/api/holdings/other?sort={sort}", headers=a).status_code == 200
    by_gain = client.get("/api/holdings/other?sort=gain&dir=desc", headers=a).json()["items"]
    assert by_gain[0]["name"] == "Painting" and by_gain[-1]["gain"] is None

    assert client.get("/api/master/other/categories", headers=a).json() == ["crypto", "Art"]
    assert client.get("/api/master/other/categories", headers=b).json() == []
    assert client.get("/api/master/other/categories").status_code == 401

    groups = client.get("/api/portfolio", headers=a).json()["groups"]
    other = next(g for g in groups if g["type"] == "other")
    assert other["label"] == "Other" and other["count"] == 3

    item_id = body["id"]
    saved = client.put(f"/api/assets/other/{item_id}", json={**VALID, "name": "BTC"}, headers=a)
    assert saved.json()["message"] == "Changes saved"
    assert client.get(f"/api/holdings/other/{item_id}", headers=a).json()["master"] is None
    assert client.get(f"/api/assets/other/{item_id}", headers=b).json()["message"] == "Other not found"

    deleted = client.delete(f"/api/assets/other/{item_id}", headers=a)
    assert deleted.json()["message"] == "Other deleted"
    restored = client.post(f"/api/assets/other/{item_id}/restore", headers=a)
    assert restored.json()["message"] == "Other restored"


def test_cross_field_error_returns_422_with_message(client, users):  # noqa: F811
    a, _, _, _ = users
    response = client.post(
        "/api/assets/other", json={**VALID, "acquired_on": "2025-12-01"}, headers=a
    )
    assert response.status_code == 422
    assert OTHER_ACQUIRED_AFTER_VALUE_ERROR in response.text
