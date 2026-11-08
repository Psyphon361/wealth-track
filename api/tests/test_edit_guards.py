"""PUT /api/assets/{type}/{id} on sold, settled and partly sold holdings (SQLite)."""

import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import HoldingExit, StockMaster
from app.services import bond_master
from app.schemas.assets import (
    HOLDING_CLOSED_DESCRIPTION,
    HOLDING_CLOSED_MESSAGE,
    SOLD_IN_PART_ERROR,
    SOLD_IN_PART_FIELDS,
)
from tests.test_exits_api import BOND, FD, FUND, GOLD, OTHER, RD, STOCK, add, asset, item, sell, settle
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import sc  # noqa: F401  (fixture: today is 2026-03-10)

MATURED_FD = {**FD, "start_date": "2024-01-01"}

# slug -> (body, partial sale arguments, protected field -> the edit that changes it; the total
# invested must keep matching quantity x price for bonds and funds, so some edits move two fields)
PARTLY = {
    "stock": (
        STOCK,
        {"quantity": 40, "price": 80},
        {
            "symbol": {"symbol": "OTHERCO"},
            "exchange": {"exchange": "BSE"},
            "quantity": {"quantity": 59},
            "avg_buy_price": {"avg_buy_price": 51},
            "buy_date": {"buy_date": "2025-01-02"},
        },
    ),
    "bond": (
        BOND,
        {"quantity": 4, "price": 1100},  # leaves 6 at 1,000 = 6,000
        {
            "isin": {"isin": "INE002A01018"},
            "quantity": {"quantity": 5, "invested_amount": 5000},
            "purchase_price": {"purchase_price": 990, "invested_amount": 5940},
            "invested_amount": {"purchase_price": 990, "invested_amount": 5940},
            "purchase_date": {"purchase_date": "2025-01-02"},
        },
    ),
    "mf": (
        FUND,
        {"quantity": 40, "price": 60},  # leaves 60 units at 40 = 2,400
        {
            "scheme_code": {"scheme_code": 102},
            "units": {"units": 59, "invested_amount": 2360},
            "avg_nav": {"avg_nav": 41, "invested_amount": 2460},
            "invested_amount": {"avg_nav": 41, "invested_amount": 2460},
            "purchase_date": {"purchase_date": "2025-06-02"},
        },
    ),
    "gold": (
        GOLD,
        {"quantity": 2.5, "price": 4000},
        {
            "metal": {"metal": "silver"},
            "purity": {"purity": "995"},
            "weight_grams": {"weight_grams": 7},
            "invested_amount": {"invested_amount": 37501},
            "purchase_date": {"purchase_date": "2025-01-02"},
        },
    ),
}


def put(c, headers, slug, item_id, body):
    return c.put(f"/api/assets/{slug}/{item_id}", json=body, headers=headers)


def stored_body(c, headers, slug, item_id, base, **changes):
    """The whole form as the Edit dialog resends it: stored values, plus the given changes."""
    stored = asset(c, headers, slug, item_id)
    return {**{key: stored[key] for key in base if key in stored}, **changes}


def sale_errors(response):
    return {tuple(e["loc"][1:]): e["msg"] for e in response.json()["detail"]}


def test_constants_cover_the_five_field_kinds():
    assert set(SOLD_IN_PART_FIELDS) == {"stock", "bond", "mf", "gold", "other"}
    assert SOLD_IN_PART_ERROR == "Sold in part: undo the sale to change this."
    assert HOLDING_CLOSED_MESSAGE == "This holding is closed"


# --- closed holdings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug,body,args",
    [
        ("stock", STOCK, {"quantity": 100, "price": 80}),
        ("bond", BOND, {"quantity": 10, "price": 1000}),
        ("gold", GOLD, {"quantity": 10, "price": 5000}),
        ("other", OTHER, {"amount": 90000}),
    ],
)
def test_sold_holding_cannot_be_edited(sc, users, slug, body, args):
    a = users[0]
    item_id = add(sc, a, slug, body)
    assert sell(sc, a, slug, item_id, **args).status_code == 201
    before = asset(sc, a, slug, item_id)
    r = put(sc, a, slug, item_id, {**body, "name": "Renamed"})
    assert r.status_code == 409
    assert r.json()["message"] == HOLDING_CLOSED_MESSAGE
    assert r.json()["description"] == HOLDING_CLOSED_DESCRIPTION
    assert asset(sc, a, slug, item_id) == before


@pytest.mark.parametrize("slug,body", [("fd", MATURED_FD), ("rd", {**RD}), ("bond", {**BOND, "maturity_date": "2025-06-01"})])
def test_settled_holding_cannot_be_edited_but_matured_one_can(sc, users, slug, body):
    a = users[0]
    item_id = add(sc, a, slug, body)
    assert item(sc, a, slug, item_id)["status"] == "matured"
    edited = {**body, "notes": "still editable"}
    assert put(sc, a, slug, item_id, edited).status_code == 200
    assert settle(sc, a, slug, item_id).status_code == 201
    before = asset(sc, a, slug, item_id)
    r = put(sc, a, slug, item_id, {**body, "notes": "after settle"})
    assert r.status_code == 409
    assert (r.json()["message"], r.json()["description"]) == (
        HOLDING_CLOSED_MESSAGE,
        HOLDING_CLOSED_DESCRIPTION,
    )
    assert asset(sc, a, slug, item_id) == before


def test_undoing_the_settlement_makes_it_editable_again(sc, users):
    a = users[0]
    fd_id = add(sc, a, "fd", MATURED_FD)
    exit_id = settle(sc, a, "fd", fd_id).json()["id"]
    assert put(sc, a, "fd", fd_id, MATURED_FD).status_code == 409
    assert sc.delete(f"/api/exits/{exit_id}", headers=a).status_code == 200
    assert put(sc, a, "fd", fd_id, {**MATURED_FD, "notes": "back"}).status_code == 200


def test_missing_or_other_users_holding_is_404(sc, users):
    a, _, b, _ = users
    stock_id = add(sc, a, "stock", STOCK)
    assert put(sc, b, "stock", stock_id, STOCK).status_code == 404
    assert put(sc, a, "stock", 9999, STOCK).status_code == 404


# --- partly sold ----------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", list(PARTLY))
def test_partly_sold_protected_fields_are_rejected_one_by_one(sc, users, slug):
    a = users[0]
    body, sale, changed = PARTLY[slug]
    item_id = add(sc, a, slug, body)
    assert sell(sc, a, slug, item_id, **sale).status_code == 201
    before = asset(sc, a, slug, item_id)
    # master_id is covered by test_partly_sold_cannot_be_pointed_at_another_security
    assert set(changed) | {"master_id"} >= set(SOLD_IN_PART_FIELDS[slug])
    assert set(changed) <= set(SOLD_IN_PART_FIELDS[slug])
    for field, change in changed.items():
        r = put(sc, a, slug, item_id, stored_body(sc, a, slug, item_id, body, **change))
        assert r.status_code == 422, (field, r.json())
        assert sale_errors(r).get((field,)) == SOLD_IN_PART_ERROR, (field, r.json())
    assert asset(sc, a, slug, item_id) == before


@pytest.mark.parametrize("slug", list(PARTLY))
def test_partly_sold_unchanged_values_and_free_fields_are_accepted(sc, users, slug):
    a = users[0]
    body, sale, _changed = PARTLY[slug]
    item_id = add(sc, a, slug, body)
    assert sell(sc, a, slug, item_id, **sale).status_code == 201
    r = put(sc, a, slug, item_id, stored_body(sc, a, slug, item_id, body))
    assert r.status_code == 200, r.json()
    free = {"notes": "kept after a sale"}
    if slug == "mf":
        free["platform"] = "Zerodha"
    else:
        free["name"] = "Renamed after sale"
    r = put(sc, a, slug, item_id, stored_body(sc, a, slug, item_id, body, **free))
    assert r.status_code == 200, r.json()
    stored = asset(sc, a, slug, item_id)
    assert all(stored[key] == value for key, value in free.items())


@pytest.mark.parametrize("slug", ["stock", "bond"])
def test_partly_sold_cannot_be_pointed_at_another_security(
    sc, users, auth_engine, monkeypatch, slug
):
    a = users[0]
    StockMaster.__table__.create(auth_engine, checkfirst=True)
    with sessionmaker(bind=auth_engine)() as session:
        session.add_all([
            StockMaster(id=1, isin="INE000A01001", kind="stock", name="Acme Ltd", nse_symbol="ACME"),
            StockMaster(id=2, isin="INE000A01002", kind="stock", name="Other Ltd", nse_symbol="OTHERCO"),
        ])  # fmt: skip
        session.commit()
    # the bond master table has a Postgres-only column, so its lookup is stubbed
    bonds = {
        1: SimpleNamespace(isin="INE000B07001", name="Test Bond 2035"),
        2: SimpleNamespace(isin="INE000B07002", name="Other Bond 2030"),
    }
    monkeypatch.setattr(bond_master, "require_bond_master", lambda _db, mid: bonds[mid])
    body = {**(STOCK if slug == "stock" else BOND), "master_id": 1}
    item_id = add(sc, a, slug, body)
    sale = {"quantity": 40, "price": 80} if slug == "stock" else {"quantity": 4, "price": 1100}
    assert sell(sc, a, slug, item_id, **sale).status_code == 201
    before = asset(sc, a, slug, item_id)
    assert before["master_id"] == 1
    # an unchanged full payload (name and symbol/isin as the master gave them) passes,
    # even when the web resends them in another case or with spaces
    same = stored_body(sc, a, slug, item_id, body)
    assert put(sc, a, slug, item_id, same).status_code == 200
    code = "symbol" if slug == "stock" else "isin"
    spaced = {**same, code: f" {str(before[code]).lower()} "}
    assert put(sc, a, slug, item_id, {**spaced, "master_id": 1}).status_code == 200
    r = put(sc, a, slug, item_id, {**same, "master_id": 2})
    assert r.status_code == 422
    errors = sale_errors(r)
    assert errors.get(("master_id",)) == SOLD_IN_PART_ERROR
    assert errors.get((code,)) == SOLD_IN_PART_ERROR
    assert asset(sc, a, slug, item_id) == before


def test_undoing_the_sale_unlocks_the_fields(sc, users):
    a = users[0]
    stock_id = add(sc, a, "stock", STOCK)
    exit_id = sell(sc, a, "stock", stock_id, quantity=40, price=80).json()["id"]
    body = stored_body(sc, a, "stock", stock_id, STOCK, avg_buy_price=51)
    assert put(sc, a, "stock", stock_id, body).status_code == 422
    assert sc.delete(f"/api/exits/{exit_id}", headers=a).status_code == 200
    body = stored_body(sc, a, "stock", stock_id, STOCK, avg_buy_price=51, quantity=70)
    assert put(sc, a, "stock", stock_id, body).status_code == 200


def test_other_checks_its_two_protected_fields(sc, users, auth_engine):
    a, user_id = users[0], users[1]
    other_id = add(sc, a, "other", OTHER)
    assert put(sc, a, "other", other_id, {**OTHER, "invested_amount": 1}).status_code == 200
    # An Other holding is sold whole (and then closed), so a sale row on an open one is made by
    # hand to cover the guard.
    with sessionmaker(bind=auth_engine)() as session:
        session.add(
            HoldingExit(
                user_id=user_id, asset_type="other", holding_id=other_id, kind="sale",
                exit_date=date(2026, 1, 15), amount=1, cost=1, destination="none",
            )
        )  # fmt: skip
        session.commit()
        assert session.scalar(select(HoldingExit.id)) is not None
    changed = put(sc, a, "other", other_id, {**OTHER, "invested_amount": 2})
    assert changed.status_code == 422
    assert sale_errors(changed) == {("invested_amount",): SOLD_IN_PART_ERROR}
    moved = put(sc, a, "other", other_id, {**OTHER, "invested_amount": 1, "acquired_on": "2024-02-01"})
    assert sale_errors(moved) == {("acquired_on",): SOLD_IN_PART_ERROR}
    free = {**OTHER, "invested_amount": 1, "current_value": 95000, "name": "Plot 2"}
    assert put(sc, a, "other", other_id, free).status_code == 200


def test_fund_with_transactions_but_no_sale_is_unchanged(sc, users):
    a = users[0]
    fund_id = add(sc, a, "mf", FUND)
    assert sc.post("/api/sips", json={
        "scheme_code": 100, "platform": "Groww", "amount": 5000, "day_of_month": 5,
        "start_date": "2026-01-05", "include_past": True, "mutual_fund_id": fund_id,
    }, headers=a).status_code in (200, 201)  # fmt: skip
    body = stored_body(sc, a, "mf", fund_id, FUND, platform="Zerodha")
    assert put(sc, a, "mf", fund_id, body).status_code == 200
    stored = asset(sc, a, "mf", fund_id)
    assert (stored["platform"], stored["units"]) == ("Zerodha", body["units"])


# --- the flag the web reads -----------------------------------------------------------------------


def test_items_expose_the_exit_the_web_derives_sold_in_part_from(sc, users):
    a = users[0]
    stock_id = add(sc, a, "stock", STOCK)
    assert item(sc, a, "stock", stock_id)["exit"] is None
    sell(sc, a, "stock", stock_id, quantity=40, price=80)
    found = item(sc, a, "stock", stock_id)
    assert found["exit"]["kind"] == "sale" and found["closed_on"] is None and found["settled"] is False
    listed = sc.get("/api/holdings/stock", headers=a).json()["items"][0]
    assert listed["exit"]["kind"] == "sale" and listed["closed_on"] is None


def test_web_constants_match_api():
    root = Path(__file__).resolve().parents[2] / "web"
    schema_ts = (root / "components/forms/schema.ts").read_text()
    guards_ts = (root / "lib/edit-guards.ts").read_text()

    def const(name):
        m = re.search(rf'export const {name} = "([^"]*)";', schema_ts)
        assert m, name
        return m.group(1)

    assert const("HOLDING_CLOSED_MESSAGE") == HOLDING_CLOSED_MESSAGE
    assert const("HOLDING_CLOSED_DESCRIPTION") == HOLDING_CLOSED_DESCRIPTION
    assert const("SOLD_IN_PART_ERROR") == SOLD_IN_PART_ERROR

    block = re.search(r"export const SOLD_IN_PART_FIELDS[^=]*=\s*\{(.*?)\n\};", guards_ts, re.S)
    assert block
    web_fields = {
        key: re.findall(r'"([^"]+)"', items)
        for key, items in re.findall(r"(\w+):\s*\[([^\]]*)\]", block.group(1))
    }
    assert web_fields == {k: list(v) for k, v in SOLD_IN_PART_FIELDS.items()}
