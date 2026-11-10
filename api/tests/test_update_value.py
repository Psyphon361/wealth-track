"""POST /api/assets/{cash|pf|other|nps}/{id}/update-value: the quick refresh of a stale figure (SQLite)."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import HoldingExit, HoldingFunding, NpsMaster
from app.schemas.assets import CashCreate, NpsCreate, OtherCreate, PfCreate
from app.services import nps
from tests.test_exits_api import CASH, OTHER, add, asset, errors, group, item, sell
from tests.test_paid_from import NPS, PF
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import sc  # noqa: F401  (fixture: today is 2026-03-10)

TODAY = "2026-03-10"
BODIES = {
    "cash": (CASH, {"balance": 2500.5}, "Balance updated"),
    "pf": (PF, {"balance": 250000}, "Balance updated"),
    "other": (OTHER, {"current_value": 95000}, "Value updated"),
}
DATE_FIELD = {"cash": "balance_date", "pf": "balance_date", "other": "value_date"}
VALUE_FIELD = {"cash": "balance", "pf": "balance", "other": "current_value"}
FULL = {"cash": CashCreate, "pf": PfCreate, "other": OtherCreate}


@pytest.fixture
def env(sc, auth_engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(nps, "sync_scheme_safely", lambda scheme_id: None)
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            NpsMaster(scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                      scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E")
        )  # fmt: skip
        session.commit()
    return sc


def post(c, headers, slug, item_id, body):
    return c.post(f"/api/assets/{slug}/{item_id}/update-value", json=body, headers=headers)


def full_form_error(slug, field, value):
    """The message the full form's model gives for a bad value of `field`."""
    base = {"cash": CASH, "pf": PF, "other": OTHER, "nps": NPS}[slug]
    model = {**FULL, "nps": NpsCreate}[slug]
    with pytest.raises(ValidationError) as exc:
        model(**{**base, field: value})
    return next(e["msg"] for e in exc.value.errors() if e["loc"][0] == field)


@pytest.mark.parametrize("slug", ["cash", "pf", "other"])
def test_updates_only_the_value_and_date(env, users, slug):
    a = users[0]
    base, change, message = BODIES[slug]
    item_id = add(env, a, slug, base)
    before = asset(env, a, slug, item_id)
    r = post(env, a, slug, item_id, {**change, DATE_FIELD[slug]: "2026-03-01"})
    assert r.status_code == 200, r.json()
    out = r.json()
    assert out["message"] == message
    assert out["description"].startswith(before["name"])
    assert out[VALUE_FIELD[slug]] == change[VALUE_FIELD[slug]]
    assert out[DATE_FIELD[slug]] == "2026-03-01"
    after = asset(env, a, slug, item_id)
    untouched = {k: v for k, v in before.items() if k not in (VALUE_FIELD[slug], DATE_FIELD[slug], "updated_at")}
    assert {k: v for k, v in after.items() if k in untouched} == untouched


def test_nps_updates_units_and_contributed(env, users):
    a = users[0]
    item_id = add(env, a, "nps", NPS)
    r = post(env, a, "nps", item_id, {"units": "1200.5", "contributed": 45000})
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "Units updated"
    row = asset(env, a, "nps", item_id)
    assert (row["units"], row["contributed"], row["start_date"]) == (1200.5, 45000, NPS["start_date"])


@pytest.mark.parametrize("slug", ["cash", "pf", "other"])
def test_missing_date_defaults_to_today(env, users, slug):
    a = users[0]
    base, change, _ = BODIES[slug]
    item_id = add(env, a, slug, base)
    assert post(env, a, slug, item_id, change).status_code == 200
    assert asset(env, a, slug, item_id)[DATE_FIELD[slug]] == TODAY


def test_cash_may_be_updated_to_zero(env, users):
    a = users[0]
    item_id = add(env, a, "cash", CASH)
    assert post(env, a, "cash", item_id, {"balance": 0}).status_code == 200
    assert asset(env, a, "cash", item_id)["balance"] == 0


@pytest.mark.parametrize(
    ("slug", "field", "value"),
    [
        ("cash", "balance", -5),
        ("cash", "balance", "12.345"),
        ("pf", "balance", 0),
        ("pf", "balance", "1.234"),
        ("other", "current_value", 0),
        ("other", "current_value", 2_000_000_000_00),
        ("nps", "units", 0),
        ("nps", "units", "1.23456"),
        ("nps", "contributed", 0),
    ],
)
def test_validation_messages_match_the_full_forms(env, users, slug, field, value):
    a = users[0]
    item_id = add(env, a, slug, {"cash": CASH, "pf": PF, "other": OTHER, "nps": NPS}[slug])
    good = {"cash": {"balance": 10}, "pf": {"balance": 10}, "other": {"current_value": 10},
            "nps": {"units": 1, "contributed": 10}}[slug]  # fmt: skip
    r = post(env, a, slug, item_id, {**good, field: value})
    assert r.status_code == 422
    loc, msg = errors(r)
    assert loc == [field] and msg == full_form_error(slug, field, value)


@pytest.mark.parametrize("slug", ["cash", "pf", "other"])
def test_date_rules_match_the_full_forms(env, users, slug):
    a = users[0]
    base, change, _ = BODIES[slug]
    item_id = add(env, a, slug, base)
    field = DATE_FIELD[slug]
    far = (date.today() + timedelta(days=60)).isoformat()
    r = post(env, a, slug, item_id, {**change, field: far})
    assert r.status_code == 422
    assert errors(r) == ([field], full_form_error(slug, field, far))
    r = post(env, a, slug, item_id, {**change, field: "1980-01-01"})
    assert r.status_code == 422
    assert errors(r) == ([field], full_form_error(slug, field, "1980-01-01"))
    assert asset(env, a, slug, item_id)[VALUE_FIELD[slug]] == base[VALUE_FIELD[slug]]


def test_other_value_date_cannot_precede_the_purchase_date(env, users):
    a = users[0]
    item_id = add(env, a, "other", OTHER)  # acquired 2024-01-01
    r = post(env, a, "other", item_id, {"current_value": 1000, "value_date": "2023-12-31"})
    assert r.status_code == 422
    assert errors(r) == (["value_date"], "Purchase date can't be after the value date")
    assert asset(env, a, "other", item_id)["current_value"] == OTHER["current_value"]


@pytest.mark.parametrize("slug", ["cash", "pf", "other", "nps"])
def test_other_users_and_deleted_holdings_are_404(env, users, slug):
    a, _, b, _ = users
    base = {"cash": CASH, "pf": PF, "other": OTHER, "nps": NPS}[slug]
    body = {"cash": {"balance": 1}, "pf": {"balance": 1}, "other": {"current_value": 1},
            "nps": {"units": 1, "contributed": 1}}[slug]  # fmt: skip
    item_id = add(env, a, slug, base)
    assert post(env, b, slug, item_id, body).status_code == 404
    assert env.delete(f"/api/assets/{slug}/{item_id}", headers=a).status_code == 200
    assert post(env, a, slug, item_id, body).status_code == 404
    assert post(env, a, slug, 99999, body).status_code == 404


def test_unknown_types_have_no_endpoint(env, users):
    a = users[0]
    assert post(env, a, "fd", 1, {"balance": 1}).status_code in (404, 405)


def test_closed_other_is_refused(env, users):
    a = users[0]
    item_id = add(env, a, "other", OTHER)
    assert sell(env, a, "other", item_id, amount=90000).status_code == 201
    r = post(env, a, "other", item_id, {"current_value": 1})
    assert r.status_code == 409
    assert r.json()["message"] == "This holding is closed"
    assert asset(env, a, "other", item_id)["current_value"] == OTHER["current_value"]


def test_ledger_rows_are_not_touched(env, users, auth_engine):
    a = users[0]
    cash_id = add(env, a, "cash", CASH)
    other_id = add(env, a, "other", OTHER)
    sold_id = add(env, a, "other", {**OTHER, "name": "Plot 2"})
    assert sell(env, a, "other", sold_id, amount=90000).status_code == 201
    with sessionmaker(bind=auth_engine)() as session:
        exits = len(session.scalars(select(HoldingExit)).all())
        fundings = len(session.scalars(select(HoldingFunding)).all())
    assert post(env, a, "cash", cash_id, {"balance": 7}).status_code == 200
    assert post(env, a, "other", other_id, {"current_value": 7}).status_code == 200
    with sessionmaker(bind=auth_engine)() as session:
        assert len(session.scalars(select(HoldingExit)).all()) == exits
        assert len(session.scalars(select(HoldingFunding)).all()) == fundings


@pytest.mark.parametrize("slug", ["cash", "pf", "other"])
def test_stale_flag_follows_the_update(env, users, slug):
    a = users[0]
    base, change, _ = BODIES[slug]
    old = {**base, DATE_FIELD[slug]: "2025-06-01"}  # more than six months before 2026-03-10
    item_id = add(env, a, slug, old)
    assert item(env, a, slug, item_id)["stale"] is True
    assert group(env, a, slug)["items"][0]["stale"] is True
    grid = env.get(f"/api/holdings/{slug}", headers=a).json()["items"]
    assert [i["stale"] for i in grid] == [True]
    # The read endpoints use the real clock, so refresh to the real today.
    assert post(env, a, slug, item_id, {**change, DATE_FIELD[slug]: date.today().isoformat()}).status_code == 200
    assert item(env, a, slug, item_id)["stale"] is False
    assert [i["stale"] for i in env.get(f"/api/holdings/{slug}", headers=a).json()["items"]] == [False]


def test_other_types_carry_no_stale_key(env, users):
    a = users[0]
    item_id = add(env, a, "nps", NPS)
    assert "stale" not in item(env, a, "nps", item_id)
    assert "stale" not in group(env, a, "nps")["items"][0]


def test_a_closed_other_is_not_stale(env, users):
    a = users[0]
    item_id = add(env, a, "other", {**OTHER, "value_date": "2025-06-01"})
    assert sell(env, a, "other", item_id, amount=90000).status_code == 201
    assert item(env, a, "other", item_id)["stale"] is False
