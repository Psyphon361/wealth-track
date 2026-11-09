"""Editing the cost of a holding bought with Paid From adjusts the cash account (SPEC §8c "Edit")."""

from decimal import Decimal

import pytest
from sqlalchemy import event, update

from app.models import HoldingFunding, MutualFund
from app.schemas.fundings import (
    PAID_FROM_EDIT_DELETED_ERROR,
    PAID_FROM_EDIT_GONE_NOTE,
    PAID_FROM_EDIT_NOT_IN_SYNC_NOTE,
    PAID_FROM_EDIT_TOO_MUCH_ERROR,
    PAID_FROM_EDIT_ZERO_ERROR,
)
from app.services import fundings
from tests.test_exits_api import BOND, FD, GOLD, OTHER, RD, STOCK, add, asset, errors, item
from tests.test_paid_from import (  # noqa: F401  (fixtures: env, db)
    NPS,
    PF,
    SOURCE,
    add_paid,
    balance,
    db,
    env,
    funding_rows,
    sell_into,
    source,
)
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND
from tests.test_sip_api import sc  # noqa: F401  (fixture)


def put(env, headers, slug, item_id, body):
    return env.put(f"/api/assets/{slug}/{item_id}", json=body, headers=headers)


def mf(amount, **extra):
    """The test fund at a cost of `amount` (invested must equal units x average NAV)."""
    return {**FUND, "avg_nav": amount / 100, "invested_amount": amount, **extra}


def bond(amount):
    """The test bond at a cost of `amount` (10 each, so a quantity of amount / 1000)."""
    return {**BOND, "quantity": amount / 1000, "invested_amount": amount}


def funded(env, a, slug, body, **cash):
    cash_id = source(env, a, **cash)
    r = add_paid(env, a, slug, body, cash_id)
    assert r.status_code == 201, r.json()
    return cash_id, r.json()["id"]


def fund_amount(db):
    [row] = funding_rows(db)
    return row.amount


def test_an_increase_takes_the_difference_and_says_so(env, db, users):
    a = users[0]
    cash_id, fd_id = funded(env, a, "fd", FD, balance=300000)
    assert balance(env, a, cash_id)[0] == 200000
    r = put(env, a, "fd", fd_id, {**FD, "principal": 125000})
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "Changes saved"
    assert r.json()["description"].endswith(" · HDFC Savings: ₹2,00,000 → ₹1,75,000")
    assert balance(env, a, cash_id) == (175000, "2026-01-01")
    assert fund_amount(db) == Decimal(125000)
    assert item(env, a, "fd", fd_id)["paid_from"]["amount"] == 125000


def test_a_decrease_puts_money_back(env, db, users):
    a = users[0]
    cash_id, bond_id = funded(env, a, "bond", BOND)
    r = put(env, a, "bond", bond_id, bond(6000))
    assert r.status_code == 200, r.json()
    assert r.json()["description"].endswith(" · HDFC Savings: ₹9,90,000 → ₹9,94,000")
    assert balance(env, a, cash_id)[0] == 994000
    assert fund_amount(db) == Decimal(6000)


def test_an_unchanged_cost_moves_nothing_and_adds_no_note(env, db, users):
    a = users[0]
    cash_id, gold_id = funded(env, a, "gold", GOLD)
    r = put(env, a, "gold", gold_id, {**GOLD, "name": "Renamed coins"})
    assert r.status_code == 200
    assert " · " not in r.json()["description"]
    assert balance(env, a, cash_id)[0] == 950000 and fund_amount(db) == Decimal(50000)


def test_stock_cost_is_quantity_times_price_and_the_error_points_at_the_edited_field(env, db, users):
    a = users[0]
    cash_id, stock_id = funded(env, a, "stock", STOCK, balance=5100)
    r = put(env, a, "stock", stock_id, {**STOCK, "quantity": 200})
    assert errors(r)[0] == ["quantity"]
    r = put(env, a, "stock", stock_id, {**STOCK, "avg_buy_price": 60})
    assert errors(r)[0] == ["avg_buy_price"]
    # Within the balance: 100 x 51 = 5,100 against 100 left plus the 5,000 already taken.
    assert put(env, a, "stock", stock_id, {**STOCK, "avg_buy_price": 51}).status_code == 200
    assert balance(env, a, cash_id)[0] == 0 and fund_amount(db) == Decimal(5100)


def test_an_increase_beyond_the_balance_is_a_422_on_the_cost_field_and_saves_nothing(env, db, users):
    a = users[0]
    cash_id, fd_id = funded(env, a, "fd", FD, balance=130000)  # 30,000 left
    r = put(env, a, "fd", fd_id, {**FD, "principal": 140000, "bank": "New Bank"})
    assert r.status_code == 422
    message = PAID_FROM_EDIT_TOO_MUCH_ERROR.format(account="HDFC Savings", shortfall="₹10,000")
    assert errors(r) == (["principal"], message)
    assert asset(env, a, "fd", fd_id)["principal"] == 100000
    assert asset(env, a, "fd", fd_id)["bank"] == "Old Bank"
    assert balance(env, a, cash_id)[0] == 30000 and fund_amount(db) == Decimal(100000)
    # Exactly the balance is fine.
    assert put(env, a, "fd", fd_id, {**FD, "principal": 130000}).status_code == 200
    assert balance(env, a, cash_id)[0] == 0


def test_a_deleted_account_refuses_a_cost_change_but_not_other_edits(env, db, users):
    a = users[0]
    cash_id, fd_id = funded(env, a, "fd", FD)
    assert env.delete(f"/api/assets/cash/{cash_id}", headers=a).status_code == 200
    r = put(env, a, "fd", fd_id, {**FD, "principal": 90000})
    assert r.status_code == 422
    assert errors(r) == (["principal"], PAID_FROM_EDIT_DELETED_ERROR.format(account="HDFC Savings"))
    assert asset(env, a, "fd", fd_id)["principal"] == 100000 and fund_amount(db) == Decimal(100000)
    notes_only = put(env, a, "fd", fd_id, {**FD, "bank": "Other Bank", "notes": "x"})
    assert notes_only.status_code == 200 and " · " not in notes_only.json()["description"]


def test_a_purged_account_saves_the_edit_and_moves_no_money(env, db, users):
    a = users[0]
    _cash_id, fd_id = funded(env, a, "fd", FD)
    db.execute(update(HoldingFunding).values(cash_holding_id=None))
    db.commit()
    paid = item(env, a, "fd", fd_id)["paid_from"]
    assert (paid["adjustable"], paid["reason"]) == (False, "account_gone")
    r = put(env, a, "fd", fd_id, {**FD, "principal": 90000})
    assert r.status_code == 200, r.json()
    assert r.json()["description"].endswith(" · " + PAID_FROM_EDIT_GONE_NOTE)
    assert asset(env, a, "fd", fd_id)["principal"] == 90000
    assert fund_amount(db) == Decimal(100000)


def test_clearing_or_zeroing_the_cost_of_a_funded_holding_is_a_422(env, db, users):
    a = users[0]
    cash_id, other_id = funded(env, a, "other", OTHER)
    cleared = {k: v for k, v in OTHER.items() if k != "invested_amount"}
    r = put(env, a, "other", other_id, cleared)
    assert r.status_code == 422
    assert errors(r) == (["invested_amount"], PAID_FROM_EDIT_ZERO_ERROR)
    assert asset(env, a, "other", other_id)["invested_amount"] == 50000
    assert balance(env, a, cash_id)[0] == 950000 and fund_amount(db) == Decimal(50000)


def test_an_unfunded_holding_edits_as_before(env, db, users):
    a = users[0]
    other_id = add(env, a, "other", OTHER)
    cleared = {k: v for k, v in OTHER.items() if k != "invested_amount"}
    r = put(env, a, "other", other_id, cleared)
    assert r.status_code == 200 and " · " not in r.json()["description"]
    stock_id = add(env, a, "stock", STOCK)
    assert put(env, a, "stock", stock_id, {**STOCK, "quantity": 300}).status_code == 200
    assert funding_rows(db) == []


def drift(db, model, holding_id, **values):
    """What SIP posting or a CAS 'update existing' does: change the cost, not the funding."""
    db.execute(update(model).where(model.id == holding_id).values(**values))
    db.commit()


def test_a_holding_out_of_sync_with_its_funding_saves_and_moves_nothing(env, db, users):
    a = users[0]
    cash_id, mf_id = funded(env, a, "mf", FUND)  # 4,000 taken
    drift(db, MutualFund, mf_id, invested_amount=Decimal(4500))  # a SIP instalment landed
    paid = item(env, a, "mf", mf_id)["paid_from"]
    assert (paid["adjustable"], paid["reason"]) == (False, "out_of_sync")
    r = put(env, a, "mf", mf_id, mf(4800))
    assert r.status_code == 200, r.json()
    note = PAID_FROM_EDIT_NOT_IN_SYNC_NOTE.format(account="HDFC Savings")
    assert r.json()["description"].endswith(" · " + note)
    assert asset(env, a, "mf", mf_id)["invested_amount"] == 4800
    assert balance(env, a, cash_id)[0] == 996000 and fund_amount(db) == Decimal(4000)
    # Even when it is a lot more than the account holds, or the account is gone.
    assert put(env, a, "mf", mf_id, mf(9000000)).status_code == 200
    assert env.delete(f"/api/assets/cash/{cash_id}", headers=a).status_code == 200
    assert put(env, a, "mf", mf_id, mf(5000)).status_code == 200


def test_a_notes_only_edit_of_an_out_of_sync_holding_has_no_note(env, db, users):
    a = users[0]
    _cash_id, mf_id = funded(env, a, "mf", FUND)
    drift(db, MutualFund, mf_id, invested_amount=Decimal(4500))
    r = put(env, a, "mf", mf_id, mf(4500, notes="just a note"))
    assert r.status_code == 200 and " · " not in r.json()["description"]


def test_deleting_and_restoring_after_an_edit_use_the_edited_amount(env, db, users):
    a = users[0]
    cash_id, fd_id = funded(env, a, "fd", FD)
    assert put(env, a, "fd", fd_id, {**FD, "principal": 150000}).status_code == 200
    assert balance(env, a, cash_id)[0] == 850000
    assert env.delete(f"/api/assets/fd/{fd_id}", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 1000000
    assert env.post(f"/api/assets/fd/{fd_id}/restore", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 850000
    assert fund_amount(db) == Decimal(150000)


def test_an_increase_on_a_reinvested_funding_is_clamped_in_the_exit_read(env, db, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    stock_id, sale = sell_into(env, a, cash_id)  # 8,000 added to the account
    r = add_paid(env, a, "bond", bond(5000), cash_id, from_exit_id=sale["id"])
    assert r.status_code == 201, r.json()
    bond_id = r.json()["id"]
    assert put(env, a, "bond", bond_id, bond(12000)).status_code == 200
    [listed] = env.get(f"/api/holdings/stock/{stock_id}/exits", headers=a).json()
    assert (listed["reinvested"], listed["left_in_account"]) == (12000, 0)
    assert balance(env, a, cash_id)[0] == 60000 + 8000 - 12000
    assert funding_rows(db)[0].from_exit_id == sale["id"]


@pytest.mark.parametrize(
    ("slug", "body", "field", "value"),
    [
        ("rd", RD, "monthly_instalment", 9000),
        ("nps", NPS, "contributed", 90000),
        ("pf", PF, "contributed", 90000),
        ("cash", {**SOURCE, "name": "Wallet", "balance": 3000}, "balance", 9000),
    ],
)
def test_running_figure_types_move_no_money_and_take_no_funding_or_cash_lock(
    env, db, users, auth_engine, monkeypatch, slug, body, field, value
):
    a = users[0]
    cash_id = source(env, a)
    holding_id = add_paid(env, a, slug, body, cash_id).json()["id"]
    after_add = balance(env, a, cash_id)
    amount = fund_amount(db)
    paid = item(env, a, slug, holding_id)["paid_from"]
    assert (paid["adjustable"], paid["reason"]) == (False, "type")

    statements: list[str] = []
    def record(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(auth_engine, "before_cursor_execute", record)
    monkeypatch.setattr(fundings, "_cash_of", lambda *args: pytest.fail("cash was locked"))
    try:
        r = put(env, a, slug, holding_id, {**body, field: value})
    finally:
        event.remove(auth_engine, "before_cursor_execute", record)
    assert r.status_code == 200, r.json()
    assert not any("FROM holding_fundings" in s for s in statements)
    assert " · " not in r.json()["description"]
    assert balance(env, a, cash_id) == after_add and fund_amount(db) == amount


def test_the_paid_from_flag_names_why_editing_will_not_move_money(env, db, users):
    a = users[0]
    cash_id, gold_id = funded(env, a, "gold", GOLD)
    assert item(env, a, "gold", gold_id)["paid_from"]["adjustable"] is True
    assert env.delete(f"/api/assets/cash/{cash_id}", headers=a).status_code == 200
    paid = item(env, a, "gold", gold_id)["paid_from"]
    assert (paid["adjustable"], paid["reason"]) == (False, "account_deleted")
    grid = env.get("/api/holdings/gold", headers=a).json()["items"]
    assert grid[0]["paid_from"]["reason"] == "account_deleted"
    live = env.get("/api/portfolio", headers=a).json()["groups"]
    gold = next(g for g in live if g["type"] == "gold")
    assert gold["items"][0]["paid_from"]["adjustable"] is False
