"""Paid from: taking a new holding's price off a Cash & Savings account (SQLite, no network)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.models import Cash, HoldingFunding, NpsMaster, Stock
from app.services import fundings, nps, purge
from tests.test_exits_api import BOND, CASH, FD, GOLD, OTHER, RD, STOCK, add, asset, errors, item
from tests.test_exits_api import sell, settle
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND
from tests.test_sip_api import sc  # noqa: F401  (fixture: today is 2026-03-10, scheme 100 exists)

NPS = {"scheme_id": "SM001003", "units": "1000.1234", "contributed": 40000, "start_date": "2025-10-01"}
PF = {
    "name": "SBI PPF", "kind": "ppf", "balance": 200000, "balance_date": "2026-01-01",
    "interest_rate": 7.1, "contributed": 150000, "opened_on": "2020-04-10",
}  # fmt: skip
NEW_CASH = {"name": "Wallet", "kind": "cash", "balance": 3000, "balance_date": "2026-02-01"}
SOURCE = {**CASH, "name": "HDFC Savings", "balance": 1000000}
CASH_ERROR = "Choose one of your accounts"
TOO_MUCH = "More than this account's balance"
NEEDS_AMOUNT = "Enter the amount invested to pay it from an account"


@pytest.fixture
def env(sc, auth_engine, monkeypatch):  # noqa: F811
    """`sc` (today is 2026-03-10) plus NPS schemes and no history sync."""
    monkeypatch.setattr(nps, "sync_scheme_safely", lambda scheme_id: None)
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            NpsMaster(scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                      scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E")
        )  # fmt: skip
        session.commit()
    return sc


@pytest.fixture
def db(env, auth_engine):
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        yield session


def source(c, headers, **overrides):
    return add(c, headers, "cash", {**SOURCE, **overrides})


def balance(c, headers, cash_id):
    row = asset(c, headers, "cash", cash_id)
    return row["balance"], row["balance_date"]


def add_paid(c, headers, slug, body, cash_id, **paid):
    return c.post(
        f"/api/assets/{slug}", json={**body, "paid_from": {"cash_id": cash_id, **paid}}, headers=headers
    )


def funding_rows(db):
    db.expire_all()
    return list(db.scalars(select(HoldingFunding).order_by(HoldingFunding.id)))


ALL_TYPES = [
    ("fd", FD, 100000, "2024-01-01"),
    ("rd", RD, 60000, "2024-01-01"),  # 12 instalments by 2026-03-10
    ("stock", STOCK, 5000, "2025-01-01"),
    ("bond", BOND, 10000, "2025-01-01"),
    ("mf", FUND, 4000, "2025-06-01"),
    ("nps", NPS, 40000, "2025-10-01"),
    ("gold", GOLD, 50000, "2025-01-01"),
    ("cash", NEW_CASH, 3000, "2026-02-01"),
    ("pf", PF, 150000, "2026-01-01"),  # contributed, not the balance
    ("other", OTHER, 50000, "2024-01-01"),
]  # fmt: skip


@pytest.mark.parametrize(("slug", "body", "amount", "funded_on"), ALL_TYPES)
def test_each_type_takes_its_invested_amount(env, db, users, slug, body, amount, funded_on):
    a = users[0]
    cash_id = source(env, a)
    r = add_paid(env, a, slug, body, cash_id)
    assert r.status_code == 201, r.json()
    assert "paid_from" not in r.json()
    new_balance, new_date = balance(env, a, cash_id)
    assert new_balance == 1000000 - amount
    assert new_date == max("2026-01-01", funded_on)

    [row] = funding_rows(db)
    assert (row.asset_type, row.holding_id, row.cash_holding_id) == (slug, r.json()["id"], cash_id)
    assert (row.amount, row.funded_on, row.from_exit_id) == (
        Decimal(amount), date.fromisoformat(funded_on), None,
    )
    assert row.prev_balance_date == date(2026, 1, 1) and row.refunded_at is None
    assert r.json()["description"].endswith(" taken from HDFC Savings")
    assert "₹" in r.json()["description"]


def test_pf_without_contributed_takes_the_balance(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    body = {k: v for k, v in PF.items() if k != "contributed"}
    assert add_paid(env, a, "pf", body, cash_id).status_code == 201
    assert balance(env, a, cash_id)[0] == 800000


def test_success_message_and_balance_date_rules(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    r = add_paid(env, a, "stock", STOCK, cash_id)
    assert r.json()["message"] == "Stock added"
    assert r.json()["description"] == "Acme Ltd · ₹5,000 taken from HDFC Savings"
    # Older purchase: the balance date stays; newer one moves it forward.
    assert balance(env, a, cash_id) == (995000, "2026-01-01")
    r = add_paid(env, a, "other", {**OTHER, "acquired_on": "2026-02-10", "value_date": "2026-03-01"}, cash_id)
    assert r.status_code == 201
    assert balance(env, a, cash_id) == (945000, "2026-02-10")
    # No start date at all: today (2026-03-10 in this fixture).
    r = add_paid(env, a, "other", {**OTHER, "name": "Art", "acquired_on": None}, cash_id)
    assert r.status_code == 201
    assert balance(env, a, cash_id) == (895000, "2026-03-10")
    assert [f.funded_on for f in funding_rows(db)][-1] == date(2026, 3, 10)


def test_the_holding_and_the_cash_account_share_one_transaction(env, db, users, monkeypatch):
    a = users[0]
    cash_id = source(env, a)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(fundings, "apply", boom)
    with pytest.raises(RuntimeError):
        add_paid(env, a, "stock", STOCK, cash_id)
    assert balance(env, a, cash_id)[0] == 1000000
    assert env.get("/api/assets/stock", headers=a).json() == []


def test_without_paid_from_nothing_changes(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    r = env.post("/api/assets/stock", json=STOCK, headers=a)
    assert r.status_code == 201
    assert r.json()["description"] == "Acme Ltd"
    assert balance(env, a, cash_id) == (1000000, "2026-01-01")
    assert funding_rows(db) == []
    assert item(env, a, "stock", r.json()["id"])["paid_from"] is None
    r = env.post("/api/assets/other", json={**OTHER, "paid_from": None}, headers=a)
    assert r.status_code == 201 and funding_rows(db) == []


# --- validation ------------------------------------------------------------------------------


def test_more_than_the_balance_is_refused_and_writes_nothing(env, db, users):
    a = users[0]
    cash_id = source(env, a, balance=4999.99)
    r = add_paid(env, a, "stock", STOCK, cash_id)
    assert r.status_code == 422
    assert errors(r) == (["paid_from", "cash_id"], TOO_MUCH)
    assert env.get("/api/assets/stock", headers=a).json() == []
    assert balance(env, a, cash_id)[0] == 4999.99 and funding_rows(db) == []
    # Exactly the balance is fine and empties the account.
    exact = source(env, a, name="Exact", balance=5000)
    assert add_paid(env, a, "stock", STOCK, exact).status_code == 201
    assert balance(env, a, exact)[0] == 0


def test_other_needs_an_invested_amount(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    body = {**OTHER, "invested_amount": None}
    r = add_paid(env, a, "other", body, cash_id)
    assert r.status_code == 422
    assert errors(r) == (["paid_from", "cash_id"], NEEDS_AMOUNT)
    assert env.get("/api/assets/other", headers=a).json() == []
    assert env.post("/api/assets/other", json=body, headers=a).status_code == 201  # not paid from


def test_an_account_that_is_not_yours_or_active_is_refused(env, db, users):
    a, _, b, _ = users
    theirs = source(env, b, name="Theirs")
    deleted = source(env, a, name="Gone")
    assert env.delete(f"/api/assets/cash/{deleted}", headers=a).status_code == 200
    for cash_id in (theirs, deleted, 99999):
        r = add_paid(env, a, "stock", STOCK, cash_id)
        assert r.status_code == 422
        assert errors(r) == (["paid_from", "cash_id"], CASH_ERROR)
    assert balance(env, b, theirs)[0] == 1000000
    assert env.get("/api/assets/stock", headers=a).json() == []


def test_a_bad_paid_from_shape_is_a_422(env, users):
    a = users[0]
    r = env.post("/api/assets/stock", json={**STOCK, "paid_from": {}}, headers=a)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "paid_from", "cash_id"]


# --- duplicates ------------------------------------------------------------------------------


def test_a_duplicate_409_debits_nothing_and_confirming_debits_once(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    assert env.post("/api/assets/stock", json=STOCK, headers=a).status_code == 201
    r = add_paid(env, a, "stock", STOCK, cash_id)
    assert r.status_code == 409
    assert balance(env, a, cash_id) == (1000000, "2026-01-01") and funding_rows(db) == []

    body = {**STOCK, "paid_from": {"cash_id": cash_id}}
    retry = env.post("/api/assets/stock?confirm_duplicate=true", json=body, headers=a)
    assert retry.status_code == 201, retry.json()
    assert balance(env, a, cash_id)[0] == 995000
    assert len(funding_rows(db)) == 1


# --- items -----------------------------------------------------------------------------------


def test_items_carry_paid_from(env, users):
    a, _, b, _ = users
    cash_id = source(env, a)
    plain = env.post("/api/assets/stock", json={**STOCK, "name": "Plain"}, headers=a).json()["id"]
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    expected = {
        "cash_holding_id": cash_id, "cash_name": "HDFC Savings", "amount": 5000, "date": "2025-01-01",
    }  # fmt: skip
    assert item(env, a, "stock", stock_id)["paid_from"] == expected
    grid = env.get("/api/holdings/stock", headers=a).json()["items"]
    assert {i["id"]: i["paid_from"] for i in grid} == {plain: None, stock_id: expected}
    stocks = next(g for g in env.get("/api/portfolio", headers=a).json()["groups"] if g["type"] == "stock")
    assert {i["id"]: i["paid_from"] for i in stocks["items"]} == {plain: None, stock_id: expected}
    assert env.get("/api/holdings/stock", headers=b).json()["items"] == []


def test_the_account_name_survives_the_account_being_deleted(env, users):
    a = users[0]
    cash_id = source(env, a)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    assert env.delete(f"/api/assets/cash/{cash_id}", headers=a).status_code == 200
    paid = item(env, a, "stock", stock_id)["paid_from"]
    assert (paid["cash_name"], paid["amount"]) == ("HDFC Savings", 5000)


def test_editing_never_changes_the_funding(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    edited = {**STOCK, "quantity": 200, "paid_from": {"cash_id": cash_id}}
    assert env.put(f"/api/assets/stock/{stock_id}", json=edited, headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 995000
    [row] = funding_rows(db)
    assert row.amount == Decimal(5000) and row.refunded_at is None


# --- delete, restore, purge --------------------------------------------------------------------


def test_delete_refunds_and_restore_debits_again(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    assert env.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 1000000
    assert funding_rows(db)[0].refunded_at is not None

    r = env.post(f"/api/assets/stock/{stock_id}/restore", headers=a)
    assert r.status_code == 200, r.json()
    assert balance(env, a, cash_id)[0] == 995000
    assert funding_rows(db)[0].refunded_at is None
    assert item(env, a, "stock", stock_id)["paid_from"]["amount"] == 5000


def test_restore_with_too_little_balance_is_a_409_and_changes_nothing(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    assert env.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200
    low = {**SOURCE, "balance": 100}
    assert env.put(f"/api/assets/cash/{cash_id}", json=low, headers=a).status_code == 200

    r = env.post(f"/api/assets/stock/{stock_id}/restore", headers=a)
    assert r.status_code == 409
    assert r.json()["message"] == "Not enough in HDFC Savings"
    assert r.json()["description"] == "Update its balance, then restore."
    assert balance(env, a, cash_id)[0] == 100
    assert env.get(f"/api/assets/stock/{stock_id}", headers=a).status_code == 404  # still deleted
    assert funding_rows(db)[0].refunded_at is not None

    high = {**SOURCE, "balance": 9000}
    assert env.put(f"/api/assets/cash/{cash_id}", json=high, headers=a).status_code == 200
    assert env.post(f"/api/assets/stock/{stock_id}/restore", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 4000


def test_a_deleted_account_is_skipped_on_refund_and_restore(env, db, users):
    a = users[0]
    cash_id = source(env, a)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    assert env.delete(f"/api/assets/cash/{cash_id}", headers=a).status_code == 200
    assert env.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200
    assert funding_rows(db)[0].refunded_at is not None
    assert env.post(f"/api/assets/stock/{stock_id}/restore", headers=a).status_code == 200
    assert funding_rows(db)[0].refunded_at is None


def test_purge_deletes_the_fundings_of_purged_holdings_only(env, db, users, auth_engine):
    a = users[0]
    cash_id = source(env, a)
    old = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    kept = add_paid(env, a, "stock", {**STOCK, "name": "Kept Ltd"}, cash_id).json()["id"]
    assert env.delete(f"/api/assets/stock/{old}", headers=a).status_code == 200
    assert env.delete(f"/api/assets/stock/{kept}", headers=a).status_code == 200
    ago = datetime.now(timezone.utc) - timedelta(days=40)
    db.execute(update(Stock).where(Stock.id == old).values(deleted_at=ago))
    db.commit()

    counts = purge.purge_deleted(db)

    assert counts["stock"] == 1 and counts["fundings"] == 1
    assert [f.holding_id for f in funding_rows(db)] == [kept]


# --- exits -----------------------------------------------------------------------------------


def sell_into(env, a, cash_id):
    stock_id = add(env, a, "stock", {**STOCK, "name": "Sold Ltd"})
    r = sell(
        env, a, "stock", stock_id, quantity=100, price=80,
        destination={"kind": "cash_existing", "cash_id": cash_id},
    )  # fmt: skip
    assert r.status_code == 201, r.json()
    return stock_id, r.json()


def test_exit_reads_show_reinvested_and_what_is_left(env, db, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    stock_id, sale = sell_into(env, a, cash_id)
    assert (sale["reinvested"], sale["left_in_account"]) == (0, 8000)

    r = add_paid(env, a, "other", OTHER, cash_id, from_exit_id=sale["id"])
    assert r.status_code == 201, r.json()
    other_id = r.json()["id"]
    assert [f.from_exit_id for f in funding_rows(db)] == [sale["id"]]

    [listed] = env.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    # 50,000 reinvested out of 8,000 added: floored at 0, never negative.
    assert (listed["cash_added"], listed["reinvested"], listed["left_in_account"]) == (8000, 50000, 0)
    summary = item(env, a, "stock", stock_id)["exit"]
    assert (summary["reinvested"], summary["left_in_account"]) == (50000, 0)

    # Deleting the holding paid from it gives the money back: nothing is reinvested any more.
    assert env.delete(f"/api/assets/other/{other_id}", headers=a).status_code == 200
    [listed] = env.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    assert (listed["reinvested"], listed["left_in_account"]) == (0, 8000)


def test_left_in_account_is_cash_added_less_reinvested(env, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    stock_id, sale = sell_into(env, a, cash_id)
    assert add_paid(env, a, "stock", STOCK, cash_id, from_exit_id=sale["id"]).status_code == 201
    [listed] = env.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    assert (listed["reinvested"], listed["left_in_account"]) == (5000, 3000)


def test_money_that_went_into_no_account_has_no_left_in_account(env, users):
    a = users[0]
    stock_id = add(env, a, "stock", STOCK)
    sale = sell(env, a, "stock", stock_id, quantity=100, price=80).json()
    assert (sale["reinvested"], sale["left_in_account"]) == (0, None)
    [listed] = env.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    assert (listed["reinvested"], listed["left_in_account"]) == (0, None)


def test_a_settlement_reports_reinvested_too(env, users):
    a = users[0]
    cash_id = source(env, a)
    fd_id = add(env, a, "fd", FD)
    r = settle(env, a, "fd", fd_id, {"kind": "cash_existing", "cash_id": cash_id})
    assert r.status_code == 201, r.json()
    assert (r.json()["reinvested"], r.json()["left_in_account"]) == (0, 108243.22)
    assert add_paid(env, a, "stock", STOCK, cash_id, from_exit_id=r.json()["id"]).status_code == 201
    exit_ = item(env, a, "fd", fd_id)["exit"]
    assert (exit_["reinvested"], exit_["left_in_account"]) == (5000, 103243.22)


def test_from_exit_id_must_be_one_of_your_exits(env, users):
    a, _, b, _ = users
    cash_id = source(env, a)
    theirs = add(env, b, "stock", STOCK)
    their_exit = sell(env, b, "stock", theirs, quantity=100, price=80).json()["id"]
    for exit_id in (their_exit, 99999):
        r = add_paid(env, a, "stock", STOCK, cash_id, from_exit_id=exit_id)
        assert r.status_code == 422
        assert errors(r) == (["paid_from", "from_exit_id"], CASH_ERROR)
    assert balance(env, a, cash_id)[0] == 1000000
    assert env.get("/api/assets/stock", headers=a).json() == []


def test_undo_is_blocked_while_the_money_is_reinvested(env, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    stock_id, sale = sell_into(env, a, cash_id)
    other_id = add_paid(env, a, "other", OTHER, cash_id, from_exit_id=sale["id"]).json()["id"]

    r = env.delete(f"/api/exits/{sale['id']}", headers=a)
    assert r.status_code == 409
    assert r.json()["message"] == "Some of this money was reinvested"
    assert r.json()["description"] == "Delete the holdings paid from it first, then undo."
    assert item(env, a, "stock", stock_id)["status"] == "sold"
    assert balance(env, a, cash_id)[0] == 60000 + 8000 - 50000

    # Deleting the holding refunds the account, which frees the undo.
    assert env.delete(f"/api/assets/other/{other_id}", headers=a).status_code == 200
    assert env.delete(f"/api/exits/{sale['id']}", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 60000


def test_undo_still_works_when_nothing_was_reinvested(env, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    _stock_id, sale = sell_into(env, a, cash_id)
    assert add_paid(env, a, "other", {**OTHER, "invested_amount": 500}, cash_id).status_code == 201
    assert env.delete(f"/api/exits/{sale['id']}", headers=a).status_code == 200


# --- settle destinations ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["renewed", "fd", ""])
def test_settle_destinations_are_only_cash_existing_cash_new_and_none(env, users, kind):
    a = users[0]
    fd_id = add(env, a, "fd", FD)
    r = settle(env, a, "fd", fd_id, {"kind": kind})
    assert r.status_code == 422
    assert errors(r) == (["destination", "kind"], "Choose where the money went")
    assert settle(env, a, "fd", fd_id, {"kind": "cash_new", "cash_name": "New"}).status_code == 201
