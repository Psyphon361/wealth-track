"""Sell, settle and undo endpoints: shapes, errors, user scoping, effects on totals (SQLite)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    HoldingExit,
    MFTransaction,
    MutualFund,
    Stock,
    StockPriceHistory,
    StockPriceLatest,
)
from app.services import exits as exits_service
from app.services import valuation
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import BODY as SIP_BODY
from tests.test_sip_api import HOLDING as FUND
from tests.test_sip_api import sc  # noqa: F401  (fixture: today is 2026-03-10, scheme 100 exists)

STOCK = {
    "name": "Acme Ltd", "exchange": "NSE", "quantity": 100, "avg_buy_price": 50,
    "buy_date": "2025-01-01",
}  # fmt: skip
BOND = {
    "name": "Test Bond 2035", "issuer": "Test Issuer", "bond_type": "corporate", "quantity": 10,
    "face_value": 1000, "purchase_price": 1000, "invested_amount": 10000,
    "purchase_date": "2025-01-01", "ytm": 8, "maturity_date": "2035-01-01",
}  # fmt: skip
GOLD = {
    "name": "Coins", "form": "coin", "metal": "gold", "purity": "999", "weight_grams": 10,
    "purchase_date": "2025-01-01", "invested_amount": 50000,
}  # fmt: skip
OTHER = {
    "name": "Plot", "category": "Property", "current_value": 80000, "value_date": "2026-01-01",
    "invested_amount": 50000, "acquired_on": "2024-01-01",
}  # fmt: skip
CASH = {"name": "HDFC Savings", "kind": "savings", "balance": 1000, "balance_date": "2026-01-01"}
FD = {
    "bank": "Old Bank", "principal": 100000, "rate": 8, "start_date": "2024-01-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
RD = {
    "bank": "RD Bank", "monthly_instalment": 5000, "rate": 6, "start_date": "2024-01-01",
    "compounding": "quarterly", "tenure_years": 1,
}  # fmt: skip
NONE = {"kind": "none"}
SELL_DAY = "2026-01-15"


def add(c, headers, slug, body):
    r = c.post(f"/api/assets/{slug}", json=body, headers=headers)
    assert r.status_code == 201, r.json()
    return r.json()["id"]


def sell(c, headers, slug, item_id, **overrides):
    body = {"date": SELL_DAY, "destination": NONE, **overrides}
    return c.post(f"/api/holdings/{slug}/{item_id}/sell", json=body, headers=headers)


def settle(c, headers, slug, item_id, destination=None, **overrides):
    body = {"destination": destination or NONE, **overrides}
    return c.post(f"/api/holdings/{slug}/{item_id}/settle", json=body, headers=headers)


def item(c, headers, slug, item_id):
    r = c.get(f"/api/holdings/{slug}/{item_id}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()["item"]


def asset(c, headers, slug, item_id):
    return c.get(f"/api/assets/{slug}/{item_id}", headers=headers).json()


def group(c, headers, slug):
    return next(g for g in c.get("/api/portfolio", headers=headers).json()["groups"] if g["type"] == slug)


def errors(response):
    first = response.json()["detail"][0]
    return first["loc"][1:], first["msg"]


# --- stocks ----------------------------------------------------------------------------------


def test_partial_stock_sale_reduces_the_holding(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    r = sell(client, a, "stock", stock_id, quantity=40, price=80, charges=20)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "Part of stock sold"
    assert body["description"] == "Acme Ltd · 40 sold for ₹3,180 · gain ₹1,180"
    assert (body["kind"], body["asset_type"], body["holding_id"]) == ("sale", "stock", stock_id)
    assert (body["amount"], body["cost"], body["charges"], body["quantity"]) == (3180, 2000, 20, 40)
    assert body["realised_gain"] == 1180 and body["date"] == SELL_DAY
    assert (body["closed"], body["remaining"], body["destination"]) == (False, 60, "none")
    assert body["cash_holding_id"] is None and body["cash_name"] is None
    assert body["sips_cancelled"] == 0

    held = asset(client, a, "stock", stock_id)
    assert held["quantity"] == 60 and held["avg_buy_price"] == 50 and held["closed_on"] is None
    shown = item(client, a, "stock", stock_id)
    assert shown["status"] == "active" and shown["invested"] == 3000
    assert shown["settled"] is False and shown["closed_on"] is None
    assert shown["exit"] == {
        "id": body["id"], "kind": "sale", "date": SELL_DAY, "quantity": 40, "amount": 3180,
        "cost": 2000, "charges": 20, "destination": "none", "cash_holding_id": None,
        "new_holding_id": None, "new_asset_type": None, "reinvested": 0, "left_in_account": None,
    }  # fmt: skip
    assert group(client, a, "stock")["totals"]["invested"] == 3000


def test_full_stock_sale_closes_it_and_leaves_the_totals(client, users):
    a = users[0]
    kept = add(client, a, "stock", {**STOCK, "name": "Kept Ltd", "quantity": 10})
    stock_id = add(client, a, "stock", STOCK)
    r = sell(client, a, "stock", stock_id, quantity=100, price=80)
    assert r.status_code == 201
    body = r.json()
    assert body["message"] == "Stock sold" and body["closed"] is True and body["remaining"] is None
    assert body["amount"] == 8000 and body["cost"] == 5000

    held = asset(client, a, "stock", stock_id)
    assert held["quantity"] == 100 and held["closed_on"] == SELL_DAY  # original quantity kept
    shown = item(client, a, "stock", stock_id)
    assert shown["status"] == "sold" and shown["closed_on"] == SELL_DAY
    assert shown["exit"]["amount"] == 8000

    stocks = group(client, a, "stock")
    assert (stocks["count"], stocks["matured_count"], stocks["closed_count"]) == (1, 1, 1)
    assert stocks["totals"]["invested"] == 500  # only the kept holding
    dash = client.get("/api/dashboard", headers=a).json()
    assert dash["total_invested"] == 500
    row = next(r for r in dash["by_type"] if r["type"] == "stock")
    assert (row["count"], row["closed_count"], row["matured_count"]) == (1, 1, 1)

    grid = client.get("/api/holdings/stock", headers=a).json()
    assert grid["total"] == 2
    assert grid["summary"]["count"] == 1 and grid["summary"]["closed_count"] == 1
    assert grid["summary"]["matured_count"] == 1 and grid["summary"]["invested"] == 500
    assert grid["facets"]["status"] == [{"value": "active", "count": 1}, {"value": "sold", "count": 1}]
    for status, expected in (("sold", [stock_id]), ("closed", [stock_id]), ("active", [kept])):
        listed = client.get(f"/api/holdings/stock?status={status}", headers=a).json()
        assert [i["id"] for i in listed["items"]] == expected
    assert client.get("/api/holdings/stock?status=matured", headers=a).json()["items"] == []
    assert client.get("/api/holdings/stock?status=bogus", headers=a).status_code == 422


def test_a_sold_holding_cannot_be_sold_again_and_is_not_a_duplicate(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    assert sell(client, a, "stock", stock_id, quantity=100, price=80).status_code == 201
    again = sell(client, a, "stock", stock_id, quantity=1, price=80)
    assert again.status_code == 409
    assert again.json()["message"] == "Already sold"
    assert again.json()["description"] == (
        "This holding has been sold. Undo the sale first if it was a mistake."
    )
    # Buying the same shares again is not flagged as a duplicate of the sold holding.
    assert client.post("/api/assets/stock", json=STOCK, headers=a).status_code == 201


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"date": "2999-01-01"}, "date", "Date can't be in the future"),
        ({"date": "2024-12-31"}, "date", "Date can't be before the purchase date"),
        ({"date": "1989-12-31"}, "date", "Date must be on or after 1 Jan 1990"),
        ({"quantity": 101}, "quantity", "Can't sell more than you hold"),
        ({"quantity": 10.5}, "quantity", "Must be a whole number"),
        ({"quantity": 0}, "quantity", "Must be greater than 0"),
        ({"quantity": 1.2345}, "quantity", "Up to 3 decimal places allowed"),
        ({"quantity": None}, "quantity", "Required"),
        ({"price": None}, "price", "Required"),
        ({"price": 0}, "price", "Must be greater than 0"),
        ({"price": 1.23456}, "price", "Up to 4 decimal places allowed"),
        ({"charges": -1}, "charges", "Can't be negative"),
        ({"charges": 1.234}, "charges", "Up to 2 decimal places allowed"),
        ({"charges": 800}, "charges", "Charges must be less than the sale value"),
        ({"destination": {"kind": "bank"}}, "kind", "Choose where the money went"),
        ({"destination": {"kind": "cash_existing"}}, "cash_id", "Choose one of your accounts"),
        ({"destination": {"kind": "cash_existing", "cash_id": 9999}}, "cash_id",
         "Choose one of your accounts"),
        ({"destination": {"kind": "cash_new"}}, "cash_name", "Required"),
        ({"destination": {"kind": "cash_new", "cash_name": "x" * 201}}, "cash_name",
         "Must be at most 200 characters"),
    ],
)  # fmt: skip
def test_sale_validation_writes_nothing(client, users, overrides, field, message):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    body = {"quantity": 10, "price": 80, **overrides}
    r = sell(client, a, "stock", stock_id, **body)
    assert r.status_code == 422, r.json()
    loc, msg = errors(r)
    assert loc[-1] == field and msg == message
    assert r.json()["message"] and r.json()["description"]
    assert asset(client, a, "stock", stock_id)["quantity"] == 100
    assert client.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json() == []


def test_sell_requires_auth_and_a_known_type(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    body = {"date": SELL_DAY, "quantity": 1, "price": 1, "destination": NONE}
    assert client.post(f"/api/holdings/stock/{stock_id}/sell", json=body).status_code == 401
    fd_id = add(client, a, "fd", FD)
    assert client.post(f"/api/holdings/fd/{fd_id}/sell", json=body, headers=a).status_code == 404
    assert client.post("/api/holdings/stock/99999/sell", json=body, headers=a).status_code == 404


# --- undo ------------------------------------------------------------------------------------


def test_undo_restores_the_holding_and_only_the_latest_can_be_undone(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    first = sell(client, a, "stock", stock_id, quantity=10, price=60).json()
    second = sell(client, a, "stock", stock_id, quantity=100 - 10, price=70).json()
    assert second["closed"] is True

    listed = client.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    assert [e["id"] for e in listed] == [second["id"], first["id"]]
    assert listed[0]["quantity"] == 90 and listed[0]["amount"] == 6300

    blocked = client.delete(f"/api/exits/{first['id']}", headers=a)
    assert blocked.status_code == 409
    assert blocked.json()["message"] == "Undo the latest one first"
    assert asset(client, a, "stock", stock_id)["quantity"] == 90  # nothing changed

    undone = client.delete(f"/api/exits/{second['id']}", headers=a)
    assert undone.status_code == 200
    assert undone.json()["message"] == "Sale undone"
    assert undone.json()["description"] == "Acme Ltd is back in your portfolio."
    held = asset(client, a, "stock", stock_id)
    assert held["quantity"] == 90 and held["closed_on"] is None
    assert item(client, a, "stock", stock_id)["status"] == "active"
    assert item(client, a, "stock", stock_id)["exit"]["id"] == first["id"]

    assert client.delete(f"/api/exits/{first['id']}", headers=a).status_code == 200
    assert asset(client, a, "stock", stock_id)["quantity"] == 100
    assert item(client, a, "stock", stock_id)["exit"] is None
    assert client.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json() == []
    assert client.delete(f"/api/exits/{first['id']}", headers=a).status_code == 404


def test_undo_of_a_partial_stock_sale_adds_back_the_shares_sold(client, users, auth_engine):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    sold = sell(client, a, "stock", stock_id, quantity=40, price=80).json()
    with sessionmaker(bind=auth_engine)() as s:  # the user edits the quantity after the sale
        s.get(Stock, stock_id).quantity = 80
        s.commit()

    assert client.delete(f"/api/exits/{sold['id']}", headers=a).status_code == 200
    held = asset(client, a, "stock", stock_id)
    assert held["quantity"] == 120 and held["avg_buy_price"] == 50 and held["closed_on"] is None


@pytest.mark.parametrize("keep_full_flag", [True, False])
def test_undo_of_a_full_sale_only_reopens_the_holding(client, users, auth_engine, keep_full_flag):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    sold = sell(client, a, "stock", stock_id, quantity=100, price=80).json()
    with sessionmaker(bind=auth_engine)() as s:
        row = s.get(HoldingExit, sold["id"])
        assert row.prev_state["full"] is True
        if not keep_full_flag:  # rows saved before the flag existed
            row.prev_state = {"quantity": "100"}
        s.commit()

    assert client.delete(f"/api/exits/{sold['id']}", headers=a).status_code == 200
    held = asset(client, a, "stock", stock_id)
    assert held["quantity"] == 100 and held["closed_on"] is None


def test_undo_of_a_partial_fund_sale_keeps_units_added_since(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = add(sc, a, "mf", FUND)  # 100 units, average NAV 40, invested 4,000
    sold = sell(sc, a, "mf", fund_id, quantity=40, price=50).json()  # 60 units, 2,400 left
    with sessionmaker(bind=auth_engine)() as s:  # a SIP instalment posted afterwards
        fund = s.get(MutualFund, fund_id)
        fund.units = Decimal(str(fund.units)) + Decimal("10")
        fund.invested_amount = Decimal(str(fund.invested_amount)) + Decimal("500")
        s.commit()

    assert sc.delete(f"/api/exits/{sold['id']}", headers=a).status_code == 200
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"]) == (110, 4500)
    assert held["avg_nav"] == 40.9091  # 4,500 / 110, 4 dp
    assert held["closed_on"] is None


# --- where the money went --------------------------------------------------------------------


def test_cash_existing_adds_the_money_and_undo_takes_it_back(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    cash_id = add(client, a, "cash", CASH)
    dest = {"kind": "cash_existing", "cash_id": cash_id}
    r = sell(client, a, "stock", stock_id, quantity=40, price=80, charges=20, destination=dest)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["destination"] == "cash" and body["cash_holding_id"] == cash_id
    assert body["cash_added"] == 3180 and body["cash_name"] == "HDFC Savings"
    assert body["description"] == "Acme Ltd · 40 sold for ₹3,180 · gain ₹1,180 · added to HDFC Savings"
    cash = asset(client, a, "cash", cash_id)
    assert cash["balance"] == 4180 and cash["balance_date"] == SELL_DAY

    undone = client.delete(f"/api/exits/{body['id']}", headers=a).json()
    assert undone["description"] == (
        "Acme Ltd is back in your portfolio. ₹3,180 was taken out of HDFC Savings."
    )
    cash = asset(client, a, "cash", cash_id)
    assert cash["balance"] == 1000 and cash["balance_date"] == "2026-01-01"


def test_cash_balance_date_never_moves_backwards(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    cash_id = add(client, a, "cash", {**CASH, "balance_date": "2026-02-01"})
    dest = {"kind": "cash_existing", "cash_id": cash_id}
    sell(client, a, "stock", stock_id, quantity=1, price=80, destination=dest)
    assert asset(client, a, "cash", cash_id)["balance_date"] == "2026-02-01"


def test_cash_new_opens_a_savings_account_and_undo_keeps_it_empty(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    dest = {"kind": "cash_new", "cash_name": "  Sale proceeds "}
    r = sell(client, a, "stock", stock_id, quantity=10, price=80, destination=dest)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["cash_name"] == "Sale proceeds" and body["cash_added"] == 800
    cash = asset(client, a, "cash", body["cash_holding_id"])
    assert (cash["name"], cash["kind"], cash["balance"], cash["balance_date"]) == (
        "Sale proceeds", "savings", 800, SELL_DAY,
    )

    undone = client.delete(f"/api/exits/{body['id']}", headers=a).json()
    assert undone["description"] == (
        "Acme Ltd is back in your portfolio. ₹800 was taken out of Sale proceeds. "
        "The account Sale proceeds was kept; delete it yourself if you don't want it."
    )
    assert asset(client, a, "cash", body["cash_holding_id"])["balance"] == 0


def test_cash_account_must_be_the_users_own(client, users):
    a, _, b, _ = users
    stock_id = add(client, a, "stock", STOCK)
    theirs = add(client, b, "cash", CASH)
    dest = {"kind": "cash_existing", "cash_id": theirs}
    r = sell(client, a, "stock", stock_id, quantity=1, price=80, destination=dest)
    assert r.status_code == 422
    assert errors(r) == (["destination", "cash_id"], "Choose one of your accounts")
    assert asset(client, b, "cash", theirs)["balance"] == 1000
    assert asset(client, a, "stock", stock_id)["quantity"] == 100


# --- bonds, gold, other ----------------------------------------------------------------------


def test_partial_bond_sale_reduces_quantity_and_invested(client, users):
    a = users[0]
    bond_id = add(client, a, "bond", BOND)
    r = sell(client, a, "bond", bond_id, quantity=4, price=1100)
    assert r.status_code == 201, r.json()
    assert r.json()["message"] == "Part of bond sold"
    assert (r.json()["amount"], r.json()["cost"], r.json()["remaining"]) == (4400, 4000, 6)
    held = asset(client, a, "bond", bond_id)
    assert (held["quantity"], held["invested_amount"], held["purchase_price"]) == (6, 6000, 1000)

    full = sell(client, a, "bond", bond_id, quantity=6, price=1000)
    assert full.json()["closed"] is True and full.json()["cost"] == 6000
    assert item(client, a, "bond", bond_id)["status"] == "sold"
    bonds = group(client, a, "bond")
    assert bonds["count"] == 0 and bonds["closed_count"] == 1 and bonds["totals"]["invested"] == 0
    listed = client.get("/api/holdings/bond?status=sold", headers=a).json()
    assert [i["id"] for i in listed["items"]] == [bond_id]
    assert client.get("/api/holdings/bond", headers=a).json()["facets"]["status"] == [
        {"value": "active", "count": 0}, {"value": "matured", "count": 0},
        {"value": "sold", "count": 1},
    ]  # fmt: skip

    assert client.delete(f"/api/exits/{full.json()['id']}", headers=a).status_code == 200
    assert item(client, a, "bond", bond_id)["status"] == "active"


def test_a_matured_bond_is_settled_not_sold(client, users):
    a = users[0]
    old = add(client, a, "bond", {**BOND, "purchase_date": "2024-01-01", "maturity_date": "2025-01-01"})
    r = sell(client, a, "bond", old, quantity=1, price=1000)
    assert r.status_code == 409
    assert r.json()["message"] == "This bond has matured"
    assert r.json()["description"] == "Record where the money went with Settle instead of selling."


def test_gold_sale_in_grams(client, users):
    a = users[0]
    gold_id = add(client, a, "gold", GOLD)
    r = sell(client, a, "gold", gold_id, quantity=2.5, price=4000)
    assert r.status_code == 201, r.json()
    assert r.json()["message"] == "Part of gold sold"
    assert r.json()["description"] == "Coins · 2.5 g sold for ₹10,000 · loss ₹2,500"
    assert (r.json()["cost"], r.json()["remaining"]) == (12500, 7.5)
    held = asset(client, a, "gold", gold_id)
    assert (held["weight_grams"], held["invested_amount"]) == (7.5, 37500)
    assert sell(client, a, "gold", gold_id, quantity=7.51, price=1).status_code == 422
    done = sell(client, a, "gold", gold_id, quantity=7.5, price=7000)
    assert done.json()["message"] == "Gold sold" and done.json()["closed"] is True
    assert item(client, a, "gold", gold_id)["status"] == "sold"


def test_other_is_sold_whole_for_an_amount(client, users):
    a = users[0]
    other_id = add(client, a, "other", OTHER)
    r = sell(client, a, "other", other_id, amount=90000, charges=1000)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "Holding sold"
    assert body["description"] == "Plot · sold for ₹89,000 · gain ₹39,000"
    assert (body["amount"], body["cost"], body["quantity"], body["closed"]) == (89000, 50000, None, True)
    assert item(client, a, "other", other_id)["status"] == "sold"
    assert group(client, a, "other")["count"] == 0

    missing = add(client, a, "other", {**OTHER, "name": "Gift"})
    r = sell(client, a, "other", missing)
    assert r.status_code == 422 and errors(r) == (["amount"], "Required")
    # A holding with no invested amount costs nothing.
    free = add(client, a, "other", {**OTHER, "name": "Coin", "invested_amount": None})
    assert sell(client, a, "other", free, amount=500).json()["cost"] == 0
    # A sale before the purchase date is rejected.
    early = sell(client, a, "other", add(client, a, "other", {**OTHER, "name": "Art"}),
                 amount=500, date="2023-12-31")  # fmt: skip
    assert early.status_code == 422
    assert errors(early) == (["date"], "Date can't be before the purchase date")


# --- mutual funds ----------------------------------------------------------------------------


def fund_item(c, headers, fund_id):
    return next(
        i for i in c.get("/api/holdings/mf", headers=headers).json()["items"] if i["id"] == fund_id
    )


def test_partial_fund_sale_writes_a_redemption_and_keeps_xirr_on_transactions(sc, users):  # noqa: F811
    a = users[0]
    fund_id = add(sc, a, "mf", FUND)  # 100 units, average NAV 40, invested 4,000
    r = sell(sc, a, "mf", fund_id, quantity=40, price=50, charges=10)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "Part of fund sold"
    assert (body["amount"], body["cost"], body["remaining"]) == (1990, 1600, 60)
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (60, 2400, 40)

    page = sc.get(f"/api/holdings/mf/{fund_id}/transactions", headers=a).json()
    assert page["total"] == 2
    redemption, opening = page["items"]
    assert (redemption["kind"], redemption["units"], redemption["amount"], redemption["date"]) == (
        "redemption", 40, 1990, SELL_DAY,
    )
    assert (opening["kind"], opening["units"], opening["amount"]) == ("purchase", 100, 4000)

    row = fund_item(sc, a, fund_id)
    assert row["xirr_basis"] == "transactions" and row["xirr_transactions"] == 2
    assert row["status"] == "active" and row["units"] == 60

    # Undo drops the redemption but keeps the opening purchase, so XIRR stays on transactions.
    assert sc.delete(f"/api/exits/{body['id']}", headers=a).status_code == 200
    assert sc.get(f"/api/holdings/mf/{fund_id}/transactions", headers=a).json()["total"] == 1
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (100, 4000, 40)
    assert fund_item(sc, a, fund_id)["xirr_basis"] == "transactions"


def test_fund_sale_costs_the_oldest_units_first(sc, users, auth_engine):  # noqa: F811
    a = users[0]
    fund_id = add(sc, a, "mf", {**FUND, "units": 20, "avg_nav": 150, "invested_amount": 3000})
    with sessionmaker(bind=auth_engine)() as s:  # two purchases: 10 units for 1,000 then 10 for 2,000
        s.add_all([
            MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 6, 1), kind="purchase",
                          amount=1000, units=10),
            MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 7, 1), kind="purchase",
                          amount=2000, units=10),
        ])  # fmt: skip
        s.commit()
    r = sell(sc, a, "mf", fund_id, quantity=15, price=200)
    assert r.json()["cost"] == 2000  # 1,000 + half of 2,000, not 15/20 of 3,000
    held = asset(sc, a, "mf", fund_id)
    assert (held["units"], held["invested_amount"], held["avg_nav"]) == (5, 1000, 200)
    # The 5 units left are the newer ones: selling them costs 1,000.
    last = sell(sc, a, "mf", fund_id, quantity=5, price=200)
    assert last.json()["cost"] == 1000 and last.json()["closed"] is True
    assert fund_item(sc, a, fund_id)["xirr_basis"] == "transactions"


def test_selling_every_unit_of_a_fund_closes_it_and_stops_its_sip(sc, users):  # noqa: F811
    a = users[0]
    sip = sc.post("/api/sips", json=SIP_BODY, headers=a).json()
    fund_id = sip["mutual_fund_id"]
    held = asset(sc, a, "mf", fund_id)
    assert held["units"] == 299.985
    r = sell(sc, a, "mf", fund_id, quantity=299.985, price=60)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["closed"] is True and body["sips_cancelled"] == 1
    assert body["amount"] == 17999.1 and body["cost"] == 15000
    assert body["description"] == "Fund A - Direct Growth · 299.985 sold for ₹17,999.10 · gain ₹2,999.10 · SIP cancelled"
    assert sc.get("/api/sips", headers=a).json()[0]["status"] == "stopped"

    row = fund_item(sc, a, fund_id)
    assert row["status"] == "sold" and row["closed_on"] == SELL_DAY
    assert row["xirr_basis"] == "transactions" and row["xirr"] is not None
    assert row["sip"] is None  # a stopped SIP is not shown on the holding
    assert group(sc, a, "mf")["count"] == 0

    undone = sc.delete(f"/api/exits/{body['id']}", headers=a).json()
    assert undone["description"] == (
        "Fund A - Direct Growth is back in your portfolio. "
        "Its SIP was left paused; resume it if you still want it."
    )
    assert sc.get("/api/sips", headers=a).json()[0]["status"] == "paused"
    assert fund_item(sc, a, fund_id)["status"] == "active"


def test_fund_units_may_have_three_decimals_only(sc, users):  # noqa: F811
    a = users[0]
    fund_id = add(sc, a, "mf", FUND)
    r = sell(sc, a, "mf", fund_id, quantity=10.0005, price=50)
    assert r.status_code == 422 and errors(r) == (["quantity"], "Up to 3 decimal places allowed")
    assert sell(sc, a, "mf", fund_id, quantity=10.005, price=50).status_code == 201


# --- settling a maturity ---------------------------------------------------------------------


def test_settle_a_cumulative_fd_defaults_to_the_maturity_value(client, users):
    a = users[0]
    fd_id = add(client, a, "fd", FD)
    before = item(client, a, "fd", fd_id)
    assert before["status"] == "matured" and before["settled"] is False
    # 1,00,000 at 8% compounded quarterly for exactly one year: 1,00,000 x 1.02^4.
    assert before["maturity_amount"] == 108243.22

    dash = client.get("/api/dashboard", headers=a).json()
    assert dash["unsettled"] == {
        "count": 1, "amount": 108243.22,
        "items": [
            {"type": "fd", "id": fd_id, "name": "Old Bank", "maturity_date": "2025-01-01",
             "amount": 108243.22}
        ],
    }  # fmt: skip

    r = settle(client, a, "fd", fd_id)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "Maturity recorded"
    assert body["description"] == "Old Bank · ₹1,08,243.22 received"
    assert (body["kind"], body["date"], body["amount"], body["cost"]) == (
        "maturity", "2025-01-01", 108243.22, 100000,
    )
    assert body["closed"] is True and body["destination"] == "none"

    after = item(client, a, "fd", fd_id)
    assert after["settled"] is True and after["status"] == "matured"
    assert after["exit"]["kind"] == "maturity" and after["exit"]["amount"] == 108243.22
    assert "maturity_amount" in after and after["maturity_amount"] is None
    assert client.get("/api/dashboard", headers=a).json()["unsettled"] == {
        "count": 0, "amount": 0, "items": [],
    }

    assert settle(client, a, "fd", fd_id).status_code == 409
    again = settle(client, a, "fd", fd_id)
    assert again.json()["message"] == "Already settled"
    assert again.json()["description"] == "Undo the settlement first if you need to change it."


def test_status_closed_filter_covers_matured_deposits(client, users):
    a = users[0]
    done = add(client, a, "fd", FD)
    live = add(client, a, "fd", {**FD, "start_date": date.today().isoformat(), "tenure_years": 3})
    for status, expected in (("closed", [done]), ("matured", [done]), ("active", [live])):
        listed = client.get(f"/api/holdings/fd?status={status}", headers=a).json()
        assert [i["id"] for i in listed["items"]] == expected, status
    grid = client.get("/api/holdings/fd", headers=a).json()
    assert grid["summary"]["closed_count"] == 1 and grid["summary"]["matured_count"] == 1
    assert grid["facets"]["status"] == [
        {"value": "active", "count": 1}, {"value": "matured", "count": 1},
    ]  # fmt: skip


def test_settle_amounts_for_payout_fd_rd_and_bond(client, users):
    a = users[0]
    payout = add(client, a, "fd", {**FD, "payout_type": "payout", "principal": 200000})
    assert settle(client, a, "fd", payout).json()["amount"] == 200000  # principal only

    rd_id = add(client, a, "rd", RD)
    rd = SimpleNamespace(
        monthly_instalment=Decimal("5000"), rate=Decimal("6"), compounding="quarterly",
        start_date=date(2024, 1, 1), tenure_years=1, tenure_months=0, tenure_days=0,
    )  # fmt: skip
    expected = valuation.value_rd(rd, date(2025, 1, 1))
    r = settle(client, a, "rd", rd_id)
    assert r.json()["amount"] == float(expected["current_value"])
    assert r.json()["cost"] == 60000

    bond = add(client, a, "bond", {**BOND, "purchase_date": "2024-01-01", "maturity_date": "2025-01-01"})
    r = settle(client, a, "bond", bond)
    assert r.json()["amount"] == 10000 and r.json()["cost"] == 10000  # 10 x face value 1,000
    assert r.json()["date"] == "2025-01-01"


def test_settle_with_your_own_date_and_amount(client, users):
    a = users[0]
    bond = add(client, a, "bond", {**BOND, "purchase_date": "2024-01-01", "maturity_date": "2025-01-01"})
    r = settle(client, a, "bond", bond, date="2025-01-03", amount=9950.5)
    assert r.status_code == 201, r.json()
    assert (r.json()["date"], r.json()["amount"]) == ("2025-01-03", 9950.5)
    assert r.json()["realised_gain"] == -49.5


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"date": "2024-12-31"}, "date", "Date can't be before the maturity date"),
        ({"date": "2999-01-01"}, "date", "Date can't be in the future"),
        ({"amount": 0}, "amount", "Must be greater than 0"),
        ({"amount": 10.123}, "amount", "Up to 2 decimal places allowed"),
    ],
)
def test_settle_validation_writes_nothing(client, users, overrides, field, message):
    a = users[0]
    fd_id = add(client, a, "fd", FD)
    r = settle(client, a, "fd", fd_id, **overrides)
    assert r.status_code == 422, r.json()
    assert errors(r) == ([field], message)
    assert item(client, a, "fd", fd_id)["settled"] is False


def test_settle_needs_a_matured_deposit_or_bond(client, users):
    a = users[0]
    live = add(client, a, "fd", {**FD, "start_date": date.today().isoformat(), "tenure_years": 3})
    r = settle(client, a, "fd", live)
    assert r.status_code == 409 and r.json()["message"] == "Not matured yet"
    assert r.json()["description"].startswith("Old Bank matures on ")
    assert settle(client, a, "stock", add(client, a, "stock", STOCK)).status_code == 404
    assert settle(client, a, "fd", 99999).status_code == 404

    sold = add(client, a, "bond", BOND)
    sell(client, a, "bond", sold, quantity=10, price=1000)
    r = settle(client, a, "bond", sold)
    assert r.status_code == 409 and r.json()["message"] == "Already sold"


def test_settle_into_an_existing_or_new_cash_account_and_undo(client, users):
    a = users[0]
    cash_id = add(client, a, "cash", CASH)
    fd_id = add(client, a, "fd", FD)
    r = settle(client, a, "fd", fd_id, {"kind": "cash_existing", "cash_id": cash_id})
    assert r.status_code == 201, r.json()
    assert r.json()["description"] == "Old Bank · ₹1,08,243.22 added to HDFC Savings"
    cash = asset(client, a, "cash", cash_id)
    assert cash["balance"] == 109243.22 and cash["balance_date"] == "2026-01-01"  # later date kept
    undone = client.delete(f"/api/exits/{r.json()['id']}", headers=a).json()
    assert undone["message"] == "Settlement undone"
    assert undone["description"] == (
        "Old Bank is back in your portfolio. ₹1,08,243.22 was taken out of HDFC Savings."
    )
    assert asset(client, a, "cash", cash_id)["balance"] == 1000
    assert item(client, a, "fd", fd_id)["settled"] is False

    r = settle(client, a, "fd", fd_id, {"kind": "cash_new", "cash_name": "Maturity money"})
    new_cash = asset(client, a, "cash", r.json()["cash_holding_id"])
    assert (new_cash["name"], new_cash["balance"], new_cash["balance_date"]) == (
        "Maturity money", 108243.22, "2025-01-01",
    )


def test_renewed_is_no_longer_a_settle_destination(client, users):
    a = users[0]
    fd_id = add(client, a, "fd", FD)
    r = settle(client, a, "fd", fd_id, {"kind": "renewed"})
    assert r.status_code == 422
    assert errors(r) == (["destination", "kind"], "Choose where the money went")
    assert item(client, a, "fd", fd_id)["settled"] is False


# --- scoping and soft delete -----------------------------------------------------------------


def test_everything_is_scoped_to_the_user(client, users):
    a, _, b, _ = users
    stock_id = add(client, a, "stock", STOCK)
    fd_id = add(client, a, "fd", FD)
    sold = sell(client, a, "stock", stock_id, quantity=10, price=80).json()
    settled = settle(client, a, "fd", fd_id).json()
    body = {"date": SELL_DAY, "quantity": 1, "price": 1, "destination": NONE}
    assert client.post(f"/api/holdings/stock/{stock_id}/sell", json=body, headers=b).status_code == 404
    assert client.post(f"/api/holdings/fd/{fd_id}/settle", json={"destination": NONE}, headers=b).status_code == 404
    assert client.get(f"/api/holdings/stock/{stock_id}/exits", headers=b).status_code == 404
    for exit_id in (sold["id"], settled["id"]):
        r = client.delete(f"/api/exits/{exit_id}", headers=b)
        assert r.status_code == 404 and r.json()["message"] == "Record not found"
    assert asset(client, a, "stock", stock_id)["quantity"] == 90
    assert item(client, a, "fd", fd_id)["settled"] is True
    # Nothing of a's shows up in b's views.
    assert client.get("/api/dashboard", headers=b).json()["unsettled"]["count"] == 0
    assert group(client, b, "stock")["items"] == []


def test_a_soft_deleted_holding_cannot_be_sold_or_settled(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    fd_id = add(client, a, "fd", FD)
    assert client.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200
    assert client.delete(f"/api/assets/fd/{fd_id}", headers=a).status_code == 200
    r = sell(client, a, "stock", stock_id, quantity=1, price=80)
    assert r.status_code == 404 and r.json()["message"] == "Holding not found"
    assert settle(client, a, "fd", fd_id).status_code == 404
    assert client.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).status_code == 404


def test_undo_of_a_soft_deleted_holding_asks_to_restore_it(client, users):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    exit_id = sell(client, a, "stock", stock_id, quantity=10, price=80).json()["id"]
    client.delete(f"/api/assets/stock/{stock_id}", headers=a)
    r = client.delete(f"/api/exits/{exit_id}", headers=a)
    assert r.status_code == 409 and r.json()["message"] == "Holding not found"
    client.post(f"/api/assets/stock/{stock_id}/restore", headers=a)
    assert client.delete(f"/api/exits/{exit_id}", headers=a).status_code == 200


def test_the_exit_row_is_stored_with_what_undo_needs(client, users, auth_engine):
    a = users[0]
    stock_id = add(client, a, "stock", STOCK)
    sell(client, a, "stock", stock_id, quantity=40, price=80, charges=20)
    with sessionmaker(bind=auth_engine)() as s:
        row = s.scalars(select(HoldingExit)).one()
    assert (row.asset_type, row.holding_id, row.kind) == ("stock", stock_id, "sale")
    assert (row.exit_date, row.amount, row.cost, row.charges) == (
        date(2026, 1, 15), Decimal("3180.00"), Decimal("2000.00"), Decimal("20.00"),
    )  # fmt: skip
    assert row.prev_state == {"quantity": "100"}


# --- stock close lookup ----------------------------------------------------------------------


@pytest.fixture
def prices(client, auth_engine):  # noqa: F811
    Base.metadata.create_all(auth_engine, tables=[StockPriceHistory.__table__, StockPriceLatest.__table__])
    with sessionmaker(bind=auth_engine)() as s:
        s.add_all([
            StockPriceHistory(master_id=7, trade_date=date(2026, 1, 9), close=Decimal("100.5")),
            StockPriceHistory(master_id=7, trade_date=date(2026, 1, 12), close=Decimal("105")),
            StockPriceLatest(
                master_id=8, price=Decimal("210.25"), prev_close=Decimal("200"),
                price_time=datetime(2026, 2, 3, 15, 30, tzinfo=timezone.utc), source="bhavcopy",
            ),
        ])  # fmt: skip
        s.commit()
    return client


def test_stock_close_on_or_before_a_date(prices, users):
    a = users[0]
    r = prices.get("/api/master/stock/7/close?date=2026-01-14", headers=a)
    assert r.status_code == 200
    assert r.json() == {"price": 105, "price_date": "2026-01-12", "source": "history"}
    r = prices.get("/api/master/stock/7/close?date=2026-01-10", headers=a)
    assert r.json() == {"price": 100.5, "price_date": "2026-01-09", "source": "history"}


def test_stock_close_falls_back_to_the_latest_close_within_a_week(prices, users):
    a = users[0]
    r = prices.get("/api/master/stock/8/close?date=2026-02-05", headers=a)
    assert r.json() == {"price": 210.25, "price_date": "2026-02-03", "source": "latest"}


def test_stock_close_404_when_nothing_is_near(prices, users):
    a = users[0]
    for path in (
        "/api/master/stock/7/close?date=2026-01-20",  # last stored close is 8 days back
        "/api/master/stock/8/close?date=2026-02-20",  # latest close is too old
        "/api/master/stock/8/close?date=2026-02-01",  # latest close is after the date
        "/api/master/stock/999/close?date=2026-01-14",
    ):
        r = prices.get(path, headers=a)
        assert r.status_code == 404, path
        assert r.json()["message"] == "Price not available"
        assert r.json()["description"] == (
            "No close for this stock on or just before this date. Enter the price yourself."
        )
    future = (date.today() + timedelta(days=1)).isoformat()
    assert prices.get(f"/api/master/stock/7/close?date={future}", headers=a).status_code == 422
    assert prices.get("/api/master/stock/7/close?date=2026-01-14").status_code == 401
