from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.assets import PF_KIND_ERROR, PPF_OPENED_ERROR, PfCreate
from app.services import networth, valuation
from tests.conftest import make_pf
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

VALID = {
    "name": "Company EPF", "kind": "epf", "balance": "100000", "balance_date": "2025-10-01",
    "interest_rate": "8.25",
}  # fmt: skip
PPF = {**VALID, "name": "SBI PPF", "kind": "ppf", "opened_on": "2020-04-10"}


def _errors(**override):
    with pytest.raises(ValidationError) as exc:
        PfCreate(**{**VALID, **override})
    return {e["loc"][0]: e["msg"] for e in exc.value.errors()}


def test_valid_pf_accepted_and_contributed_optional():
    pf = PfCreate(**VALID)
    assert pf.balance == Decimal("100000") and pf.contributed is None and pf.opened_on is None


def test_bad_kind():
    assert _errors(kind="nps") == {"kind": PF_KIND_ERROR}
    assert PF_KIND_ERROR == "Choose an account type"


def test_interest_rate_required():
    data = {k: v for k, v in VALID.items() if k != "interest_rate"}
    with pytest.raises(ValidationError):
        PfCreate(**data)


def test_ppf_requires_opened_on():
    assert _errors(kind="ppf") == {"opened_on": PPF_OPENED_ERROR}
    assert PPF_OPENED_ERROR == "Enter the opening date"


def test_epf_drops_opened_on():
    assert PfCreate(**{**VALID, "opened_on": "2020-04-10"}).opened_on is None
    assert PfCreate(**{**VALID, "kind": "vpf", "opened_on": "2020-04-10"}).opened_on is None


def test_accrual_is_simple_interest_on_days_since_balance_date():
    pf = make_pf(balance=Decimal("100000"), interest_rate=Decimal("8.25"))
    out = valuation.value_pf(pf, date(2026, 10, 24))  # 365 days
    assert out["accrued_interest"] == Decimal("8250.00")
    assert out["current_value"] == Decimal("108250.00")
    out = valuation.value_pf(pf, date(2025, 1, 1))  # before balance_date
    assert out["accrued_interest"] == Decimal("0.00") and out["current_value"] == Decimal("100000.00")
    assert valuation.value_pf(pf, date(2025, 10, 24))["accrued_interest"] == Decimal("0.00")


def test_invested_without_contributed_equals_current():
    out = valuation.value_pf(make_pf(), date(2026, 10, 24))
    assert out["invested"] == out["current_value"] and out["gain"] == Decimal("0.00")
    assert out["xirr"] is None and out["status"] == "active" and out["maturity_date"] is None


def test_invested_with_contributed():
    pf = make_pf(contributed=Decimal("90000"))
    out = valuation.value_pf(pf, date(2026, 10, 24))
    assert out["invested"] == Decimal("90000.00")
    assert out["gain"] == Decimal("18250.00")


def test_ppf_maturity_april_and_march_opening():
    april = make_pf(kind="ppf", opened_on=date(2020, 4, 10))
    march = make_pf(kind="ppf", opened_on=date(2021, 3, 15))
    assert valuation.value_pf(april, date(2026, 1, 1))["maturity_date"] == date(2036, 4, 1)
    assert valuation.value_pf(march, date(2026, 1, 1))["maturity_date"] == date(2036, 4, 1)


def test_ppf_extended_until():
    pf = make_pf(kind="ppf", opened_on=date(2020, 4, 10))
    ext = lambda d: valuation.value_pf(pf, d)["extended_until"]  # noqa: E731
    assert ext(date(2036, 3, 31)) is None
    assert ext(date(2036, 4, 1)) == date(2041, 4, 1)
    assert ext(date(2038, 6, 15)) == date(2041, 4, 1)
    assert ext(date(2041, 3, 31)) == date(2041, 4, 1)
    assert ext(date(2041, 4, 1)) == date(2046, 4, 1)


def test_pf_status_always_active_and_no_extension_for_other_kinds():
    ppf = make_pf(kind="ppf", opened_on=date(2020, 4, 10))
    for d in (date(2036, 3, 31), date(2036, 4, 1), date(2050, 1, 1)):
        assert valuation.value_pf(ppf, d)["status"] == "active"
    epf = make_pf()
    out = valuation.value_pf(epf, date(2050, 1, 1))
    assert out["status"] == "active" and out["extended_until"] is None


def test_networth_zero_before_balance_date_and_accrues_after():
    pf = make_pf(balance_date=date(2026, 10, 10), balance=Decimal("100000"))
    result = networth.build_history(
        "1m", date(2026, 10, 31), {"pf": [pf]}, {}, {}, {}, (Decimal("0"), Decimal("0"))
    )
    by_date = {p["date"]: p for p in result["points"]}
    assert by_date["2026-10-09"]["current"] == Decimal("0.00")
    assert by_date["2026-10-10"]["current"] == Decimal("100000.00")
    assert by_date["2026-10-20"]["current"] == Decimal("100226.03")
    assert by_date["2026-10-20"]["invested"] == Decimal("100226.03")


def test_crud_list_and_holdings(client, users):  # noqa: F811
    a, _, b, _ = users
    created = client.post("/api/assets/pf", json=PPF, headers=a)
    assert created.status_code == 201
    body = created.json()
    assert body["kind"] == "ppf" and body["opened_on"] == "2020-04-10"
    assert body["contributed"] is None and body["interest_rate"] == 8.25

    assert len(client.get("/api/assets/pf", headers=a).json()) == 1
    assert client.get("/api/assets/pf", headers=b).json() == []

    holdings = client.get("/api/holdings/pf", headers=a).json()
    assert holdings["total"] == 1
    assert holdings["items"][0]["maturity_date"] == "2036-04-01"
    assert client.get("/api/holdings/pf?sort=maturity_date", headers=a).status_code == 200

    epf = client.post("/api/assets/pf", json={**VALID, "opened_on": "2020-04-10"}, headers=a)
    assert epf.status_code == 201 and epf.json()["opened_on"] is None

    assert client.delete(f"/api/assets/pf/{body['id']}", headers=a).status_code == 200


def test_ppf_without_opened_on_returns_422(client, users):  # noqa: F811
    a, _, _, _ = users
    bad = {k: v for k, v in PPF.items() if k != "opened_on"}
    response = client.post("/api/assets/pf", json=bad, headers=a)
    assert response.status_code == 422
    assert PPF_OPENED_ERROR in response.text
