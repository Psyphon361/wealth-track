"""Regression tests for real bugs the money machine found (now fixed), as deterministic sequences.

1. Cash delete/restore: a soft-deleted Paid From account is still refunded and debited.
2. A holding with a sale or settlement can't be deleted (it would leave the sale's money behind).
"""

import pytest
from sqlalchemy import text

from tests.stateful.world import sqlite_harness

STOCK = {
    "name": "Probe Stock", "exchange": "NSE", "quantity": 3, "avg_buy_price": "10.00",
    "buy_date": "2025-01-01",
}  # fmt: skip
CASH = {"name": "Probe Savings", "kind": "savings", "balance": "100.00", "balance_date": "2026-01-01"}
FD = {
    "bank": "Probe Bank", "principal": "1000.00", "rate": 7, "start_date": "2023-01-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
Q = {"confirm_duplicate": "true"}


@pytest.fixture
def world(auth_settings, monkeypatch):
    with sqlite_harness(monkeypatch) as harness:
        harness.reset()
        yield harness


def ok(response, status=(200, 201)):
    assert response.status_code in status, response.text
    return response.json()


def balance(h, cash_id):
    return float(h.scalar("SELECT balance FROM cash_holdings WHERE id = :i", i=cash_id))


def refunded(h, stock_id):
    return h.scalar(
        "SELECT refunded_at FROM holding_fundings WHERE asset_type = 'stock' AND holding_id = :i",
        i=stock_id,
    )


def setup_paid_holding(h):
    """Cash A = 100; a stock costing 30 is paid from A (A = 70)."""
    cash = ok(h.call("POST", "/api/assets/cash", params=Q, json=CASH))["id"]
    stock = ok(
        h.call("POST", "/api/assets/stock", params=Q, json={**STOCK, "paid_from": {"cash_id": cash}})
    )["id"]
    assert balance(h, cash) == 70
    return cash, stock


def detail(response):
    body = response.json()["detail"]
    return body["message"], body["description"]


def test_delete_account_then_holding_refunds_the_deleted_account(world):
    h = world
    cash, stock = setup_paid_holding(h)
    ok(h.call("DELETE", f"/api/assets/cash/{cash}"))
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))
    assert balance(h, cash) == 100
    assert refunded(h, stock) is not None
    ok(h.call("POST", f"/api/assets/cash/{cash}/restore"))
    ok(h.call("POST", f"/api/assets/stock/{stock}/restore"))
    assert balance(h, cash) == 70


def test_restore_holding_while_account_deleted_debits_the_deleted_account(world):
    h = world
    cash, stock = setup_paid_holding(h)
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))
    assert balance(h, cash) == 100
    ok(h.call("DELETE", f"/api/assets/cash/{cash}"))
    ok(h.call("POST", f"/api/assets/stock/{stock}/restore"))
    assert balance(h, cash) == 70
    assert refunded(h, stock) is None
    ok(h.call("POST", f"/api/assets/cash/{cash}/restore"))
    assert balance(h, cash) == 70


def test_short_restore_with_deleted_account_is_409_and_changes_nothing(world):
    h = world
    cash, stock = setup_paid_holding(h)
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))
    # drain the account to 10 so the 30 can't be taken again, then delete it
    ok(h.call("PUT", f"/api/assets/cash/{cash}", json={**CASH, "balance": "10.00"}))
    ok(h.call("DELETE", f"/api/assets/cash/{cash}"))
    r = h.call("POST", f"/api/assets/stock/{stock}/restore")
    assert r.status_code == 409, r.text
    message, description = detail(r)
    assert message == "Not enough in Probe Savings"
    assert description == (
        "Restore Probe Savings from Recently deleted and add ₹20 to it, then restore."
    )
    assert balance(h, cash) == 10
    assert refunded(h, stock) is not None
    assert h.scalar("SELECT deleted_at FROM stocks WHERE id = :i", i=stock) is not None


def test_short_restore_with_active_account_keeps_the_old_wording(world):
    h = world
    cash, stock = setup_paid_holding(h)
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))
    ok(h.call("PUT", f"/api/assets/cash/{cash}", json={**CASH, "balance": "10.00"}))
    r = h.call("POST", f"/api/assets/stock/{stock}/restore")
    assert r.status_code == 409, r.text
    assert detail(r) == ("Not enough in Probe Savings", "Update its balance, then restore.")
    assert balance(h, cash) == 10


def test_purged_account_moves_no_money(world):
    h = world
    cash, stock = setup_paid_holding(h)
    # the account was purged for good: its row is gone and the funding's link is NULL
    with h.engine.begin() as conn:
        conn.execute(text("UPDATE holding_fundings SET cash_holding_id = NULL"))
        conn.execute(text("DELETE FROM cash_holdings WHERE id = :i"), {"i": cash})
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))
    assert refunded(h, stock) is not None
    ok(h.call("POST", f"/api/assets/stock/{stock}/restore"))
    assert refunded(h, stock) is None


def test_delete_after_sale_is_refused_and_balances_unchanged(world):
    h = world
    cash = ok(h.call("POST", "/api/assets/cash", params=Q, json=CASH))["id"]
    stock = ok(h.call("POST", "/api/assets/stock", params=Q, json=STOCK))["id"]
    ok(
        h.call(
            "POST", f"/api/holdings/stock/{stock}/sell",
            json={
                "date": "2025-06-01", "quantity": 3, "price": "20.00",
                "destination": {"kind": "cash_existing", "cash_id": cash},
            },
        )
    )  # fmt: skip
    assert balance(h, cash) == 160
    r = h.call("DELETE", f"/api/assets/stock/{stock}")
    assert r.status_code == 409, r.text
    assert detail(r) == ("Undo the sale first", "Delete this holding after you undo its sale.")
    assert balance(h, cash) == 160
    assert h.scalar("SELECT deleted_at FROM stocks WHERE id = :i", i=stock) is None


def test_delete_after_partial_sale_is_refused_and_undo_makes_it_deletable(world):
    h = world
    stock = ok(h.call("POST", "/api/assets/stock", params=Q, json=STOCK))["id"]
    sold = ok(
        h.call(
            "POST", f"/api/holdings/stock/{stock}/sell",
            json={"date": "2025-06-01", "quantity": 1, "price": "20.00", "destination": {"kind": "none"}},
        )
    )  # fmt: skip
    assert h.call("DELETE", f"/api/assets/stock/{stock}").status_code == 409
    ok(h.call("DELETE", f"/api/exits/{sold['id']}"))
    ok(h.call("DELETE", f"/api/assets/stock/{stock}"))


def test_delete_after_settlement_is_refused_with_settlement_wording(world):
    h = world
    fd = ok(h.call("POST", "/api/assets/fd", params=Q, json=FD))["id"]
    ok(h.call("POST", f"/api/holdings/fd/{fd}/settle", json={"destination": {"kind": "none"}}))
    r = h.call("DELETE", f"/api/assets/fd/{fd}")
    assert r.status_code == 409, r.text
    assert detail(r) == (
        "Undo the settlement first",
        "Delete this holding after you undo its settlement.",
    )
