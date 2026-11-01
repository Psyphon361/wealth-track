from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from app.models import NpsMaster, NpsNavHistory, NpsNavLatest
from app.schemas.assets import NPS_SCHEME_ERROR, NpsCreate
from app.services import networth, nps, valuation
from tests.conftest import make_nps
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

VALID = {
    "scheme_id": "SM001003", "units": "1000.1234", "contributed": "40000",
    "start_date": "2025-10-01",
}  # fmt: skip


def _errors(**override):
    with pytest.raises(ValidationError) as exc:
        NpsCreate(**{**VALID, **override})
    return {e["loc"][0]: e["msg"] for e in exc.value.errors()}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Creating a holding schedules a history sync; record it instead of fetching."""
    calls = []
    monkeypatch.setattr(nps, "sync_scheme_safely", calls.append)
    return calls


@pytest.fixture
def masters(auth_engine, client):  # noqa: F811
    """Two schemes in the (SQLite) master; only the first has a latest NAV."""
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add_all([
            NpsMaster(scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                      scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E"),
            NpsMaster(scheme_id="SM002005", pfm_code="PFM002", pfm_name="UTI Pension Fund",
                      scheme_name="UTI SCHEME G - TIER II", tier="II", asset_class="G"),
        ])
        session.flush()
        session.add(NpsNavLatest(scheme_id="SM001003", nav=Decimal("50"), nav_date=date(2026, 10, 30)))
        session.add(NpsNavHistory(scheme_id="SM001003", nav_date=date(2026, 10, 29), nav=Decimal("49")))
        session.commit()
    return auth_engine


def test_valid_nps_accepted():
    nps_in = NpsCreate(**VALID)
    assert nps_in.units == Decimal("1000.1234") and nps_in.contributed == Decimal("40000")


def test_scheme_required_message():
    for data in ({k: v for k, v in VALID.items() if k != "scheme_id"}, {**VALID, "scheme_id": "  "}):
        with pytest.raises(ValidationError) as exc:
            NpsCreate(**data)
        assert [(e["loc"][0], e["msg"]) for e in exc.value.errors()] == [("scheme_id", NPS_SCHEME_ERROR)]
    assert NPS_SCHEME_ERROR == "Choose a scheme"


def test_units_and_contributed_rules():
    assert _errors(units="0") == {"units": "Must be greater than 0"}
    assert _errors(units="1.00001") == {"units": "Up to 4 decimal places allowed"}
    assert _errors(units="20000000") == {"units": "Must be at most 1 crore"}
    assert _errors(contributed="0") == {"contributed": "Must be greater than 0"}
    assert _errors(contributed="1.234") == {"contributed": "Up to 2 decimal places allowed"}
    assert _errors(contributed="2000000000") == {"contributed": "Must be at most ₹100 crore"}


def test_start_date_rules():
    assert _errors(start_date="1980-01-01") == {"start_date": "Date must be on or after 1 Jan 1990"}
    assert _errors(start_date="2999-01-01") == {"start_date": "Date can be at most 30 days in the future"}
    assert "start_date" in _errors(start_date="")


def test_value_at_nav_with_day_change():
    out = valuation.value_nps(
        make_nps(units=Decimal("1000"), contributed=Decimal("40000")), date(2026, 10, 31),
        nav=Decimal("50"), nav_date=date(2026, 10, 30),
        prev_nav=Decimal("49"), prev_nav_date=date(2026, 10, 29),
    )  # fmt: skip
    assert out["current_value"] == Decimal("50000.00") and out["invested"] == Decimal("40000.00")
    assert out["gain"] == Decimal("10000.00") and out["gain_pct"] == Decimal("25.00")
    assert out["nav"] == Decimal("50.0000") and out["nav_date"] == date(2026, 10, 30)
    assert out["day_change"] == Decimal("1000.00") and out["day_change_pct"] == Decimal("2.04")
    assert out["status"] == "active" and "xirr" not in out


def test_no_nav_valued_at_contributed():
    out = valuation.value_nps(make_nps(), date(2026, 10, 31))
    assert out["current_value"] == out["invested"] == Decimal("40000.00")
    assert out["gain"] == Decimal("0.00") and out["nav"] is None and out["day_change"] is None


def test_unknown_scheme_returns_422(client, users, masters):  # noqa: F811
    a, _, _, _ = users
    response = client.post("/api/assets/nps", json={**VALID, "scheme_id": "SM999999"}, headers=a)
    assert response.status_code == 422
    assert NPS_SCHEME_ERROR in response.text and "scheme_id" in response.text
    assert client.get("/api/assets/nps", headers=a).json() == []


def test_missing_scheme_returns_422(client, users, masters):  # noqa: F811
    a, _, _, _ = users
    bad = {k: v for k, v in VALID.items() if k != "scheme_id"}
    response = client.post("/api/assets/nps", json=bad, headers=a)
    assert response.status_code == 422 and NPS_SCHEME_ERROR in response.text


def test_crud_scoping_and_history_sync_scheduled(client, users, masters, no_network):  # noqa: F811
    a, _, b, _ = users
    created = client.post("/api/assets/nps", json=VALID, headers=a)
    assert created.status_code == 201
    body = created.json()
    assert body["message"] == "NPS added" and body["description"] == "SBI PENSION FUND SCHEME E - TIER I"
    assert body["scheme_name"] == "SBI PENSION FUND SCHEME E - TIER I" and body["pfm_name"] == "SBI Pension Funds"
    assert body["tier"] == "I" and body["asset_class"] == "E" and body["units"] == 1000.1234
    assert no_network == ["SM001003"]

    assert len(client.get("/api/assets/nps", headers=a).json()) == 1
    assert client.get("/api/assets/nps", headers=b).json() == []
    assert client.get(f"/api/assets/nps/{body['id']}", headers=b).status_code == 404

    moved = client.put(
        f"/api/assets/nps/{body['id']}", json={**VALID, "scheme_id": "SM002005"}, headers=a
    )
    assert moved.status_code == 200
    assert moved.json()["scheme_name"] == "UTI SCHEME G - TIER II" and moved.json()["tier"] == "II"
    assert no_network == ["SM001003", "SM002005"]

    assert client.delete(f"/api/assets/nps/{body['id']}", headers=a).status_code == 200


_real_sync_safely = nps.sync_scheme_safely


def test_sync_failure_does_not_fail_create(client, users, masters, monkeypatch):  # noqa: F811
    from app import db

    def boom(_scheme_id):
        raise RuntimeError("source down")

    a, _, _, _ = users
    monkeypatch.setattr(db, "SessionLocal", sessionmaker(bind=masters, expire_on_commit=False))
    monkeypatch.setattr(nps, "fetch_history", boom)
    monkeypatch.setattr(nps, "sync_scheme_safely", _real_sync_safely)
    assert client.post("/api/assets/nps", json=VALID, headers=a).status_code == 201
    assert len(client.get("/api/assets/nps", headers=a).json()) == 1


def test_holdings_values_filters_sort_and_detail(client, users, masters):  # noqa: F811
    a, _, _, _ = users
    one = client.post("/api/assets/nps", json=VALID, headers=a).json()
    two = client.post(
        "/api/assets/nps",
        json={**VALID, "scheme_id": "SM002005", "units": "200", "contributed": "5000"},
        headers=a,
    ).json()

    data = client.get("/api/holdings/nps", headers=a).json()
    assert data["total"] == 2
    first, second = data["items"]
    assert first["id"] == one["id"] and first["current_value"] == 50006.17  # default current_value desc
    assert first["nav"] == 50 and first["day_change"] == 1000.12
    assert second["current_value"] == 5000 and second["nav"] is None  # no NAV: at contributed
    assert data["summary"]["invested"] == 45000 and data["summary"]["count"] == 2
    facets = data["facets"]
    assert [f["value"] for f in facets["pfm_name"]] == ["SBI Pension Funds", "UTI Pension Fund"]
    assert {f["value"]: f["count"] for f in facets["tier"]} == {"I": 1, "II": 1}
    assert [f["value"] for f in facets["asset_class"]] == ["E", "C", "G", "A", "other"]

    def ids(query):
        r = client.get(f"/api/holdings/nps?{query}", headers=a)
        assert r.status_code == 200
        return [i["id"] for i in r.json()["items"]]

    assert ids("tier=II") == [two["id"]]
    assert ids("asset_class=E") == [one["id"]]
    assert ids("pfm_name=UTI Pension Fund") == [two["id"]]
    assert ids("q=uti") == [two["id"]]
    assert ids("sort=units&dir=asc") == [two["id"], one["id"]]
    assert ids("sort=scheme_name&dir=asc") == [one["id"], two["id"]]
    assert ids("sort=nav&dir=desc") == [one["id"], two["id"]]  # nulls last
    for key in ("pfm_name", "contributed", "gain", "start_date"):
        assert client.get(f"/api/holdings/nps?sort={key}", headers=a).status_code == 200

    detail = client.get(f"/api/holdings/nps/{one['id']}", headers=a).json()
    assert detail["item"]["current_value"] == 50006.17
    assert detail["master"] == {
        "scheme_id": "SM001003", "scheme_name": "SBI PENSION FUND SCHEME E - TIER I",
        "pfm_name": "SBI Pension Funds", "tier": "I", "asset_class": "E", "nav": 50.0,
        "nav_date": "2026-10-30",
    }  # fmt: skip

    group = next(g for g in client.get("/api/portfolio", headers=a).json()["groups"] if g["type"] == "nps")
    assert group["label"] == "NPS" and group["count"] == 2
    types = [g["type"] for g in client.get("/api/portfolio", headers=a).json()["groups"]]
    assert types.index("nps") == types.index("mf") + 1


def test_master_get_by_id(client, users, masters):  # noqa: F811
    a, _, _, _ = users
    found = client.get("/api/master/nps/SM002005", headers=a)
    assert found.status_code == 200
    assert found.json()["nav"] is None and found.json()["pfm_name"] == "UTI Pension Fund"
    missing = client.get("/api/master/nps/SM999999", headers=a)
    assert missing.status_code == 404 and missing.json()["message"] == "Scheme not found"


TODAY = date(2026, 10, 31)


def _history(holdings, navs):
    return networth.build_history(
        "1m", TODAY, {"nps": holdings}, {}, {}, {}, (Decimal("0"), Decimal("0")), None, navs
    )


def test_networth_uses_nav_on_or_before_and_excludes_before_start():
    holding = make_nps(
        scheme_id="S1", units=Decimal("100"), contributed=Decimal("4000"), start_date=date(2026, 10, 10)
    )
    navs = {"S1": [(date(2026, 10, 12), Decimal("41")), (date(2026, 10, 20), Decimal("42"))]}
    by_date = {p["date"]: p for p in _history([holding], navs)["points"]}
    assert by_date["2026-10-09"]["current"] == Decimal("0.00")
    assert by_date["2026-10-10"]["current"] == Decimal("4000.00")  # no NAV on/before: contributed
    assert by_date["2026-10-12"]["current"] == Decimal("4100.00")
    assert by_date["2026-10-19"]["current"] == Decimal("4100.00")
    assert by_date["2026-10-25"]["current"] == Decimal("4200.00")
    assert by_date["2026-10-25"]["invested"] == Decimal("4000.00")


def test_networth_without_any_history_values_at_contributed():
    holding = make_nps(scheme_id="S1", contributed=Decimal("4000"), start_date=date(2026, 10, 10))
    by_date = {p["date"]: p for p in _history([holding], {})["points"]}
    assert by_date["2026-10-20"]["current"] == Decimal("4000.00")
    assert networth.earliest_start({"nps": [holding]}) == date(2026, 10, 10)


def test_held_scheme_ids_comes_from_holdings(client, users, masters):  # noqa: F811
    a, _, _, _ = users
    with sessionmaker(bind=masters, expire_on_commit=False)() as session:
        assert nps.held_scheme_ids(session) == set()
        client.post("/api/assets/nps", json=VALID, headers=a)
        client.post("/api/assets/nps", json=VALID, headers=a)
        assert nps.held_scheme_ids(session) == {"SM001003"}


def test_networth_nps_linear_build_up_to_anchor():
    holding = make_nps(
        scheme_id="S1", units=Decimal("100"), contributed=Decimal("4000"),
        start_date=date(2026, 10, 10), updated_at=datetime(2026, 10, 20, 9, 0),
    )  # fmt: skip
    navs = {"S1": [(date(2026, 10, 10), Decimal("40"))]}
    by_date = {p["date"]: p for p in _history([holding], navs)["points"]}
    assert by_date["2026-10-15"]["invested"] == Decimal("2000.00")
    assert by_date["2026-10-15"]["current"] == Decimal("2000.00")  # 50 units x 40
    assert by_date["2026-10-20"]["invested"] == Decimal("4000.00")
    assert by_date["2026-10-25"]["invested"] == Decimal("4000.00")
    assert by_date["2026-10-25"]["current"] == Decimal("4000.00")


def test_networth_nps_anchor_before_start_is_full():
    holding = make_nps(
        scheme_id="S1", contributed=Decimal("4000"), start_date=date(2026, 10, 10),
        updated_at=datetime(2026, 9, 1),
    )  # fmt: skip
    by_date = {p["date"]: p for p in _history([holding], {})["points"]}
    assert by_date["2026-10-10"]["invested"] == Decimal("4000.00")


def test_networth_nps_without_nav_uses_scaled_invested():
    holding = make_nps(
        scheme_id="S1", contributed=Decimal("4000"), start_date=date(2026, 10, 10),
        updated_at=datetime(2026, 10, 30),
    )  # fmt: skip
    by_date = {p["date"]: p for p in _history([holding], {})["points"]}
    assert by_date["2026-10-20"]["invested"] == Decimal("2000.00")
    assert by_date["2026-10-20"]["current"] == Decimal("2000.00")
