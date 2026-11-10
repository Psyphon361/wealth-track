"""Real concurrency tests on Postgres: two requests racing on the same rows (marker pg).

Every test forces a true overlap (see helpers_t3.py): the first operation is held INSIDE its
lock, the second is observed waiting on a lock, then the first is released. The assertions are the
money invariants on committed data (no negative cash, one exit per sale, cash conserved, no orphaned
rows) plus the exact status the loser must get. Seeding goes through the real HTTP endpoints.
"""

import threading
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import Cash, MutualFund
from app.services import exits as exits_service
from app.services import fundings, purge
from app.services import sip as sip_service
from tests.pg.conftest import run_concurrently
from tests.pg.helpers_t3 import (
    FD,
    FUND,
    STOCK,
    World,
    assert_clean,
    cash_body,
    check_invariants,
    hold_after,
    hold_before_commit,
    staged,
    statuses,
    stock_body,
)

pytestmark = pytest.mark.pg


@pytest.fixture
def world(pg_app):
    return World(pg_app)


def detail(response) -> str:
    """Message text of an error response (the API's own message or the validation message)."""
    body = response.json()["detail"]
    if isinstance(body, list):
        return body[0]["msg"]
    return body["message"] if isinstance(body, dict) else str(body)


# --- (1) sell vs sell -----------------------------------------------------------------------------


def test_sell_vs_sell_whole_holding_one_exit_loser_gets_409(world, monkeypatch):
    stock = world.add("stock", STOCK)
    cash = world.add_cash(balance=1000)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate,
        lambda: world.sell_stock(stock, 100, 80, to_cash=cash),
        lambda: world.sell_stock(stock, 100, 80, to_cash=cash),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert len(world.exits("stock", stock)) == 1
    assert world.holding("stocks", stock).closed_on is not None
    assert world.balance(cash) == Decimal("9000")  # 1000 + 100 x 80, credited once
    check_invariants(world)


def test_sell_vs_sell_part_then_too_many_loser_gets_422(world, monkeypatch):
    stock = world.add("stock", STOCK)
    cash = world.add_cash(balance=0)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate,
        lambda: world.sell_stock(stock, 60, 80, to_cash=cash),
        lambda: world.sell_stock(stock, 60, 80, to_cash=cash),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 422], (ra.text, rb.text)
    assert detail(rb) == "Can't sell more than you hold"
    assert world.holding("stocks", stock).quantity == 40
    assert len(world.exits("stock", stock)) == 1
    assert world.balance(cash) == Decimal("4800")
    check_invariants(world)


def test_two_part_sales_that_fit_both_land_in_turn(world, monkeypatch):
    stock = world.add("stock", STOCK)
    cash = world.add_cash(balance=0)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate,
        lambda: world.sell_stock(stock, 30, 80, to_cash=cash),
        lambda: world.sell_stock(stock, 50, 80, to_cash=cash),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 201]
    assert world.holding("stocks", stock).quantity == 20
    assert len(world.exits("stock", stock)) == 2
    assert world.balance(cash) == Decimal("6400")
    check_invariants(world)


# --- (2) sell vs delete, delete vs restore ----------------------------------------------------------


def test_sell_held_then_delete_waits_and_is_refused_because_the_holding_was_sold(world, monkeypatch):
    stock = world.add("stock", STOCK)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate, lambda: world.sell_stock(stock, 40), lambda: world.delete("stock", stock)
    )
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert world.holding("stocks", stock).deleted_at is None
    assert len(world.exits("stock", stock)) == 1
    check_invariants(world)


def test_delete_held_then_sell_waits_and_gets_404(world, monkeypatch):
    stock = world.add("stock", STOCK)
    cash = world.add_cash(balance=1000)
    gate = hold_after(monkeypatch, fundings, "refund")
    a, b = staged(
        world.engine, gate,
        lambda: world.delete("stock", stock),
        lambda: world.sell_stock(stock, 40, 80, to_cash=cash),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.exits() == []
    assert world.balance(cash) == Decimal("1000")  # nothing credited
    check_invariants(world)


def funded_stock(world, cash_balance=100000, price_qty=100):
    cash = world.add_cash(balance=cash_balance)
    r = world.add_paid("stock", stock_body("Funded Ltd", price_qty), cash)  # 50 x qty
    assert r.status_code == 201, r.text
    return cash, r.json()["id"]


def test_delete_vs_restore_of_a_funded_holding_in_both_orders(world, monkeypatch):
    cash, stock = funded_stock(world)  # 100000 - 5000
    assert world.balance(cash) == Decimal("95000")
    # Live holding: delete is held, restore finds nothing deleted (it does not wait) -> 404.
    gate = hold_after(monkeypatch, fundings, "refund")
    a, b = staged(
        world.engine, gate, lambda: world.delete("stock", stock),
        lambda: world.restore("stock", stock), expect_block=False,
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.balance(cash) == Decimal("100000")
    check_invariants(world)
    # Deleted holding: restore is held, a delete finds nothing live -> 404.
    gate = hold_after(monkeypatch, fundings, "restore")
    a, b = staged(
        world.engine, gate, lambda: world.restore("stock", stock),
        lambda: world.delete("stock", stock), expect_block=False,
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.balance(cash) == Decimal("95000")
    check_invariants(world)


def test_two_deletes_refund_once(world, monkeypatch):
    cash, stock = funded_stock(world)
    gate = hold_after(monkeypatch, fundings, "refund")
    a, b = staged(
        world.engine, gate, lambda: world.delete("stock", stock), lambda: world.delete("stock", stock)
    )
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.balance(cash) == Decimal("100000")  # refunded once, not twice
    check_invariants(world)


def test_two_restores_debit_once(world, monkeypatch):
    cash, stock = funded_stock(world)
    assert world.delete("stock", stock).status_code == 200
    gate = hold_after(monkeypatch, fundings, "restore")
    a, b = staged(
        world.engine, gate, lambda: world.restore("stock", stock), lambda: world.restore("stock", stock)
    )
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.balance(cash) == Decimal("95000")  # debited once, not twice
    check_invariants(world)


# --- (3) undo vs undo, undo vs reinvest ----------------------------------------------------------------


def sold_into_cash(world, cash_balance=100000):
    cash = world.add_cash(balance=cash_balance)
    stock = world.add("stock", STOCK)
    sale = world.sell_stock(stock, 100, 80, to_cash=cash)  # +8000
    assert sale.status_code == 201, sale.text
    assert world.balance(cash) == Decimal(cash_balance) + 8000
    return cash, stock, sale.json()["id"]


def test_undo_vs_undo_of_the_same_exit_takes_the_money_back_once(world, monkeypatch):
    cash, stock, exit_id = sold_into_cash(world)
    gate = hold_after(monkeypatch, exits_service, "undo_exit")
    a, b = staged(world.engine, gate, lambda: world.undo(exit_id), lambda: world.undo(exit_id))
    assert statuses(*assert_clean(a, b)) == [200, 404]
    assert world.exits() == []
    assert world.balance(cash) == Decimal("100000")  # 8000 taken back once
    assert world.holding("stocks", stock).closed_on is None
    check_invariants(world)


def test_undo_held_then_reinvest_from_that_exit_is_refused(world, monkeypatch):
    cash, stock, exit_id = sold_into_cash(world)
    gate = hold_after(monkeypatch, exits_service, "undo_exit")
    a, b = staged(
        world.engine, gate, lambda: world.undo(exit_id),
        lambda: world.add_paid("stock", stock_body("Reinvest Ltd", 10), cash, from_exit_id=exit_id),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [200, 422], (ra.text, rb.text)
    assert world.count("stocks") == 1  # the reinvested stock was not created
    assert world.fundings() == []
    assert world.balance(cash) == Decimal("100000")
    check_invariants(world)


def test_reinvest_held_then_undo_of_that_exit_is_refused(world, monkeypatch):
    cash, stock, exit_id = sold_into_cash(world)
    gate = hold_after(monkeypatch, fundings, "plan")
    a, b = staged(
        world.engine, gate,
        lambda: world.add_paid("stock", stock_body("Reinvest Ltd", 10), cash, from_exit_id=exit_id),
        lambda: world.undo(exit_id),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert detail(rb) == "Some of this money was reinvested"
    assert len(world.exits("stock", stock)) == 1
    funding = world.fundings()
    assert len(funding) == 1 and funding[0].from_exit_id == exit_id and funding[0].refunded_at is None
    assert world.balance(cash) == Decimal("107500")  # 100000 + 8000 - 500
    check_invariants(world)


# --- (4) SIP posting ---------------------------------------------------------------------------------------


@pytest.fixture
def fund_world(world):
    world.seed_funds()
    return world


def sip_transactions(world, sip_id: int):
    return world.rows(
        "SELECT mutual_fund_id, txn_date FROM mf_transactions WHERE sip_id = :s ORDER BY txn_date", s=sip_id
    )


def test_post_due_waits_for_a_full_sale_and_does_not_post_into_the_sold_fund(fund_world, monkeypatch):
    w = fund_world
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate,
        lambda: w.sell("mf", fund, quantity=100, price=60, date="2026-03-10"),
        w.post_due,
    )  # fmt: skip
    sale, posted = assert_clean(a, b)
    assert sale.status_code == 201, sale.text
    assert posted == {sip: 3}  # the three instalments still posted (a SIP outlives a sold fund)
    sold = w.holding("mutual_funds", fund)
    assert sold.closed_on is not None and sold.units == Decimal("100") and sold.invested_amount == Decimal("4000")
    assert w.scalar("SELECT count(*) FROM mf_transactions WHERE mutual_fund_id = :f AND sip_id IS NOT NULL", f=fund) == 0
    funds = w.rows("SELECT id FROM mutual_funds WHERE scheme_code = 100 AND closed_on IS NULL")
    assert len(funds) == 1 and funds[0].id != fund
    assert w.scalar("SELECT mutual_fund_id FROM mf_sips WHERE id = :s", s=sip) == funds[0].id
    assert len(sip_transactions(w, sip)) == 3
    assert len(w.exits("mf", fund)) == 1
    check_invariants(w)


def test_sale_waits_for_post_due_and_sells_the_posted_units(fund_world, monkeypatch):
    w = fund_world
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund)
    gate = hold_after(monkeypatch, sip_service, "nav_for_due", lambda a, k: k.get("fetch") is False)
    a, b = staged(
        w.engine, gate, w.post_due,
        lambda: w.sell("mf", fund, quantity=10, price=60, date="2026-03-10"),
    )  # fmt: skip
    posted, sale = assert_clean(a, b)
    assert posted == {sip: 3}
    assert sale.status_code == 201, sale.text
    assert w.count("mutual_funds") == 1
    assert len(sip_transactions(w, sip)) == 3
    # 100 opening + 3 x 99.995 posted - 10 sold, held on the one fund.
    assert w.holding("mutual_funds", fund).units == Decimal("100") + 3 * Decimal("99.995") - 10
    check_invariants(w)


def test_two_post_due_runs_make_one_fresh_holding_and_no_duplicate_instalment(fund_world, monkeypatch):
    w = fund_world
    sip = w.add_sip(None)  # unlinked, no holding of the fund: both runs would start a new one
    barrier = threading.Barrier(2, timeout=10)
    original = sip_service._active_target

    def after_target(session, sip_row):
        found = original(session, sip_row)
        barrier.wait()  # both runs have now chosen "no holding" (neither has written anything)
        return found

    monkeypatch.setattr(sip_service, "_active_target", after_target)
    a, b = run_concurrently(w.post_due, w.post_due)
    results = assert_clean(a, b)
    assert sum(sum(r.values()) for r in results) == 3, results  # posted once, not twice
    funds = w.rows("SELECT id FROM mutual_funds WHERE scheme_code = 100")
    assert len(funds) == 1
    assert w.scalar("SELECT mutual_fund_id FROM mf_sips WHERE id = :s", s=sip) == funds[0].id
    txns = sip_transactions(w, sip)
    assert len(txns) == 3 and len({t.txn_date for t in txns}) == 3
    check_invariants(w)


def test_two_post_due_runs_on_a_sip_linked_to_a_sold_fund(fund_world, monkeypatch):
    w = fund_world
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund)
    assert w.sell("mf", fund, quantity=100, price=60, date="2026-03-10").status_code == 201
    gate = hold_after(monkeypatch, sip_service, "_active_target")
    a, b = staged(w.engine, gate, w.post_due, w.post_due)  # B waits on the sold fund's lock
    results = assert_clean(a, b)
    assert sum(sum(r.values()) for r in results) == 3, results
    funds = w.rows("SELECT id FROM mutual_funds WHERE scheme_code = 100 AND closed_on IS NULL")
    assert len(funds) == 1 and w.count("mutual_funds") == 2
    assert len(sip_transactions(w, sip)) == 3
    check_invariants(w)


# --- (5) Paid From --------------------------------------------------------------------------------------


def test_two_paid_froms_that_exceed_the_balance_only_one_succeeds(world, monkeypatch):
    cash = world.add_cash(balance=8000)
    gate = hold_after(monkeypatch, fundings, "plan")
    a, b = staged(
        world.engine, gate,
        lambda: world.add_paid("stock", stock_body("First Ltd", 100), cash),  # 5000
        lambda: world.add_paid("stock", stock_body("Second Ltd", 100), cash),  # 5000
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 422], (ra.text, rb.text)
    assert detail(rb) == "More than this account's balance"
    assert world.count("stocks") == 1 and len(world.fundings()) == 1
    assert world.balance(cash) == Decimal("3000")
    check_invariants(world)


def test_paid_from_held_then_cash_edit_waits_and_wins(world, monkeypatch):
    cash = world.add_cash(balance=100000)
    gate = hold_after(monkeypatch, fundings, "plan")
    a, b = staged(
        world.engine, gate,
        lambda: world.add_paid("stock", stock_body("Funded Ltd", 100), cash),
        lambda: world.put("cash", cash, cash_body(balance=1000)),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 200]
    assert world.balance(cash) == Decimal("1000")  # the edit set the balance after the debit
    assert world.count("stocks") == 1 and len(world.fundings()) == 1
    check_invariants(world, ledger=False)


def test_cash_edit_held_then_paid_from_sees_the_new_balance(world):
    cash = world.add_cash(balance=100000)
    from app.db import SessionLocal

    with hold_before_commit(SessionLocal, lambda s: any(isinstance(o, Cash) for o in s.dirty)) as gate:
        a, b = staged(
            world.engine, gate,
            lambda: world.put("cash", cash, cash_body(balance=1000)),
            lambda: world.add_paid("stock", stock_body("Funded Ltd", 100), cash),  # needs 5000
        )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [200, 422], (ra.text, rb.text)  # not debited from the stale 100000
    assert detail(rb) == "More than this account's balance"
    assert world.count("stocks") == 0 and world.fundings() == []
    assert world.balance(cash) == Decimal("1000")


# --- (6) settle vs settle, CAS --------------------------------------------------------------------------------


def test_settle_vs_settle_of_the_same_fd_pays_once(world, monkeypatch):
    cash = world.add_cash(balance=0)
    fd = world.add("fd", FD)
    dest = {"kind": "cash_existing", "cash_id": cash}
    gate = hold_after(monkeypatch, exits_service, "record_settlement")
    a, b = staged(
        world.engine, gate, lambda: world.settle("fd", fd, dest), lambda: world.settle("fd", fd, dest)
    )
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert detail(rb) == "Already settled"
    exits = world.exits("fd", fd)
    assert len(exits) == 1 and exits[0].cash_added > 0
    assert world.balance(cash) == exits[0].cash_added
    check_invariants(world)


def cas_body(fund: int, units: int = 120, avg_nav: int = 45, statement_to: str = "2026-02-20") -> dict:
    return {
        "statement_to": statement_to,
        "rows": [
            {
                "action": "update", "holding_id": fund, "scheme_code": 100, "scheme_name": "Fund A",
                "category": "equity", "units": units, "avg_nav": avg_nav,
                "invested_amount": units * avg_nav, "purchase_date": "2025-06-01", "transactions": [],
            }
        ],
    }  # fmt: skip


def cas_commit(world, body):
    return world.call("POST", "/api/import/cas/commit", json=body)


def test_sale_held_then_cas_commit_refuses_the_sold_fund(fund_world, monkeypatch):
    w = fund_world
    fund = w.add("mf", FUND)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        w.engine, gate,
        lambda: w.sell("mf", fund, quantity=10, price=60, date="2026-03-10"),
        lambda: cas_commit(w, cas_body(fund)),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 422], (ra.text, rb.text)
    assert "Sales are recorded for this fund here" in rb.json()["description"]
    held = w.holding("mutual_funds", fund)
    assert held.units == Decimal("90") and held.invested_amount == Decimal("3600")  # CAS changed nothing
    check_invariants(w)


def test_cas_commit_held_then_sale_sells_the_imported_units(fund_world):
    w = fund_world
    fund = w.add("mf", FUND)
    from app.db import SessionLocal

    with hold_before_commit(SessionLocal, lambda s: any(isinstance(o, MutualFund) for o in s.dirty)) as gate:
        a, b = staged(
            w.engine, gate,
            lambda: cas_commit(w, cas_body(fund)),
            lambda: w.sell("mf", fund, quantity=20, price=60, date="2026-03-10"),
        )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [200, 201], (ra.text, rb.text)
    assert w.holding("mutual_funds", fund).units == Decimal("100")  # 120 imported - 20 sold
    check_invariants(w)


# --- extras -------------------------------------------------------------------------------------------------


def test_sale_into_cash_held_then_paid_from_the_same_cash(world, monkeypatch):
    cash = world.add_cash(balance=1000)
    stock = world.add("stock", STOCK)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate,
        lambda: world.sell_stock(stock, 100, 80, to_cash=cash),  # +8000
        lambda: world.add_paid("stock", stock_body("Funded Ltd", 100), cash),  # -5000 (needs the sale)
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 201]
    assert world.balance(cash) == Decimal("4000")
    check_invariants(world)


def test_paid_from_held_then_sale_into_the_same_cash(world, monkeypatch):
    cash = world.add_cash(balance=6000)
    stock = world.add("stock", STOCK)
    gate = hold_after(monkeypatch, fundings, "plan")
    a, b = staged(
        world.engine, gate,
        lambda: world.add_paid("stock", stock_body("Funded Ltd", 100), cash),  # -5000
        lambda: world.sell_stock(stock, 100, 80, to_cash=cash),  # +8000
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 201]
    assert world.balance(cash) == Decimal("9000")
    check_invariants(world)


def test_cash_delete_held_then_sale_into_it_is_refused(world, monkeypatch):
    cash = world.add_cash(balance=1000)
    stock = world.add("stock", STOCK)
    gate = hold_after(monkeypatch, fundings, "refund")
    a, b = staged(
        world.engine, gate, lambda: world.delete("cash", cash),
        lambda: world.sell_stock(stock, 100, 80, to_cash=cash),
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [200, 422], (ra.text, rb.text)
    assert world.exits() == [] and world.holding("stocks", stock).closed_on is None
    assert world.balance(cash) == Decimal("1000")
    check_invariants(world)


def test_sale_into_cash_held_then_cash_delete_waits(world, monkeypatch):
    cash = world.add_cash(balance=1000)
    stock = world.add("stock", STOCK)
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate, lambda: world.sell_stock(stock, 100, 80, to_cash=cash),
        lambda: world.delete("cash", cash),
    )  # fmt: skip
    assert statuses(*assert_clean(a, b)) == [201, 200]
    assert world.holding("cash_holdings", cash).deleted_at is not None
    assert world.balance(cash) == Decimal("9000")  # the sale landed before the delete
    check_invariants(world)


def test_undo_held_then_a_new_part_sale_runs_on_the_restored_holding(world, monkeypatch):
    stock = world.add("stock", STOCK)
    first = world.sell_stock(stock, 40, 80)
    assert first.status_code == 201
    exit_id = first.json()["id"]
    gate = hold_after(monkeypatch, exits_service, "undo_exit")
    a, b = staged(
        world.engine, gate, lambda: world.undo(exit_id), lambda: world.sell_stock(stock, 30, 80)
    )
    assert statuses(*assert_clean(a, b)) == [200, 201]
    exits = world.exits("stock", stock)
    assert len(exits) == 1 and exits[0].id != exit_id  # only the new sale remains
    assert world.holding("stocks", stock).quantity == 70
    check_invariants(world)


def test_part_sale_held_then_undo_of_the_earlier_sale_is_refused(world, monkeypatch):
    stock = world.add("stock", STOCK)
    first = world.sell_stock(stock, 40, 80)
    exit_id = first.json()["id"]
    gate = hold_after(monkeypatch, exits_service, "record_sale")
    a, b = staged(
        world.engine, gate, lambda: world.sell_stock(stock, 30, 80), lambda: world.undo(exit_id)
    )
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert detail(rb) == "Undo the latest one first"
    assert len(world.exits("stock", stock)) == 2
    assert world.holding("stocks", stock).quantity == 30
    check_invariants(world)


def test_undo_held_then_delete_of_the_holding_waits(world, monkeypatch):
    cash, stock, exit_id = sold_into_cash(world)
    gate = hold_after(monkeypatch, exits_service, "undo_exit")
    a, b = staged(world.engine, gate, lambda: world.undo(exit_id), lambda: world.delete("stock", stock))
    assert statuses(*assert_clean(a, b)) == [200, 200]
    assert world.holding("stocks", stock).deleted_at is not None
    assert world.exits() == [] and world.balance(cash) == Decimal("100000")
    check_invariants(world)


def test_undo_of_a_legacy_deleted_sold_holding_is_refused_because_the_holding_is_gone(world):
    cash, stock, exit_id = sold_into_cash(world)
    assert world.delete("stock", stock).status_code == 409  # the API no longer deletes a sold holding
    with world.engine.begin() as conn:  # legacy state: sold, then deleted
        conn.execute(text("UPDATE stocks SET deleted_at = now() WHERE id = :i"), {"i": stock})
    rb = world.undo(exit_id)
    assert rb.status_code == 409, rb.text
    assert detail(rb) == "Holding not found"
    assert len(world.exits("stock", stock)) == 1 and world.balance(cash) == Decimal("108000")
    check_invariants(world)


def test_restore_held_then_paid_from_that_drains_the_cash_is_refused(world, monkeypatch):
    cash, stock = funded_stock(world, cash_balance=10000)  # 10000 - 5000
    assert world.delete("stock", stock).status_code == 200  # refunded: 10000
    gate = hold_after(monkeypatch, fundings, "restore")
    a, b = staged(
        world.engine, gate, lambda: world.restore("stock", stock),  # -5000 again
        lambda: world.add_paid("stock", stock_body("Drain Ltd", 160), cash),  # needs 8000 > 5000
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [200, 422], (ra.text, rb.text)
    assert world.balance(cash) == Decimal("5000")
    check_invariants(world)


def test_paid_from_held_then_restore_of_a_funded_holding_is_refused(world, monkeypatch):
    cash, stock = funded_stock(world, cash_balance=10000)
    assert world.delete("stock", stock).status_code == 200  # 10000
    gate = hold_after(monkeypatch, fundings, "plan")
    a, b = staged(
        world.engine, gate,
        lambda: world.add_paid("stock", stock_body("Drain Ltd", 160), cash),  # -8000 -> 2000
        lambda: world.restore("stock", stock),  # needs 5000
    )  # fmt: skip
    ra, rb = assert_clean(a, b)
    assert statuses(ra, rb) == [201, 409], (ra.text, rb.text)
    assert world.holding("stocks", stock).deleted_at is not None  # stays deleted
    assert world.balance(cash) == Decimal("2000")
    check_invariants(world)


def sip_fund_world(w: World):
    """A fund with a SIP that has only the 5 Mar instalment left to post (Jan and Feb were posted)."""
    fund = w.add("mf", FUND)
    sip = w.add_sip(fund, last_posted_on=date(2026, 2, 5))
    return fund, sip


def test_post_due_held_then_cas_commit_keeps_the_new_instalment(fund_world, monkeypatch):
    w = fund_world
    fund, sip = sip_fund_world(w)
    gate = hold_after(monkeypatch, sip_service, "nav_for_due", lambda a, k: k.get("fetch") is False)
    a, b = staged(w.engine, gate, w.post_due, lambda: cas_commit(w, cas_body(fund)))
    posted, imported = assert_clean(a, b)
    assert posted == {sip: 1}
    assert imported.status_code == 200, imported.text
    # statement units + the 5 Mar instalment (dated after the statement) it left in place
    assert w.holding("mutual_funds", fund).units == Decimal("120") + Decimal("99.995")
    assert len(sip_transactions(w, sip)) == 1
    check_invariants(w)


def test_cas_commit_held_then_post_due_adds_on_top(fund_world):
    w = fund_world
    fund, sip = sip_fund_world(w)
    from app.db import SessionLocal

    with hold_before_commit(SessionLocal, lambda s: any(isinstance(o, MutualFund) for o in s.dirty)) as gate:
        a, b = staged(w.engine, gate, lambda: cas_commit(w, cas_body(fund)), w.post_due)
    imported, posted = assert_clean(a, b)
    assert imported.status_code == 200, imported.text
    assert posted == {sip: 1}
    assert w.holding("mutual_funds", fund).units == Decimal("120") + Decimal("99.995")
    assert len(sip_transactions(w, sip)) == 1
    check_invariants(w)


def deleted_long_ago(world):
    """A funded stock deleted 40 days ago (past the 30-day retention), refunded."""
    cash, stock = funded_stock(world)
    assert world.delete("stock", stock).status_code == 200
    with world.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("UPDATE stocks SET deleted_at = now() - interval '40 days' WHERE id = :i"), {"i": stock})
    return cash, stock


def run_purge(world):
    with world.session() as s:
        return purge.purge_deleted(s)


def test_restore_held_then_purge_must_not_strip_the_restored_holding(world, monkeypatch):
    cash, stock = deleted_long_ago(world)
    gate = hold_after(monkeypatch, fundings, "restore")
    a, b = staged(world.engine, gate, lambda: world.restore("stock", stock), lambda: run_purge(world))
    ra, _counts = assert_clean(a, b)
    assert ra.status_code == 200
    assert world.holding("stocks", stock).deleted_at is None  # restored and kept
    funding = world.fundings()
    assert len(funding) == 1 and funding[0].refunded_at is None  # its funding record kept
    assert world.balance(cash) == Decimal("95000")
    check_invariants(world)


def test_purge_held_then_restore_gets_404(world):
    cash, stock = deleted_long_ago(world)
    with hold_before_commit(world.session, lambda s: True) as gate:
        a, b = staged(world.engine, gate, lambda: run_purge(world), lambda: world.restore("stock", stock))
    counts, restore = assert_clean(a, b)
    assert counts["stock"] == 1
    assert restore.status_code == 404
    assert world.holding("stocks", stock) is None and world.fundings() == []
    assert world.balance(cash) == Decimal("100000")
    check_invariants(world)
