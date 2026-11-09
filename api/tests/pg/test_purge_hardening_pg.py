"""Purge hardening on Postgres (marker pg): lock ordering against restore, and the lock timeout."""

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.config import settings
from app.services import purge
from tests.pg.helpers_t3 import (
    STOCK,
    Gate,
    World,
    assert_clean,
    check_invariants,
    staged,
)

pytestmark = pytest.mark.pg

PF = {"name": "SBI PPF", "kind": "ppf", "balance": 5000, "balance_date": "2026-01-01", "interest_rate": 7.1,
      "opened_on": "2020-04-01"}


@pytest.fixture
def world(pg_app):
    return World(pg_app)


def run_purge(world):
    with world.session() as s:
        return purge.purge_deleted(s)


def age(world, *tables):
    with world.engine.begin() as conn:
        for table in tables:
            conn.execute(text(f"UPDATE {table} SET deleted_at = now() - interval '40 days'"))  # noqa: S608


def chain_world(world):
    """Stock S sold into cash C (exit E); pf O paid from C out of E (funding F); then S, O and C
    are all deleted and past retention. F points at E and at C, both of which the purge deletes
    (FK SET NULL locks F), and O is what a restore wants (locks O, then F)."""
    cash = world.add_cash(balance=1000)
    stock = world.add("stock", STOCK)
    sale = world.sell_stock(stock, 100, 80, to_cash=cash)
    assert sale.status_code == 201, sale.text
    exit_id = sale.json()["id"]
    paid = world.add_paid("pf", PF, cash, from_exit_id=exit_id)
    assert paid.status_code == 201, paid.text
    pf = paid.json()["id"]
    for slug, item in (("pf", pf), ("stock", stock), ("cash", cash)):
        assert world.delete(slug, item).status_code == 200
    age(world, "pf_holdings", "stocks", "cash_holdings")
    funding = world.fundings()
    assert len(funding) == 1 and funding[0].from_exit_id == exit_id
    assert funding[0].cash_holding_id == cash and funding[0].refunded_at is not None
    return cash, stock, pf


def hold_after_last_lock(monkeypatch) -> Gate:
    """Hold the purge once it has locked its LAST type (cash), inside its transaction."""
    original = purge.lock_purgeable_ids
    gate = Gate()

    def wrapper(session, model, cutoff):
        ids = original(session, model, cutoff)
        if model.__tablename__ == "cash_holdings":
            gate.hold()
        return ids

    monkeypatch.setattr(purge, "lock_purgeable_ids", wrapper)
    return gate


def test_purge_vs_restore_of_a_funded_holding_does_not_deadlock(world, monkeypatch):
    cash, stock, pf = chain_world(world)
    gate = hold_after_last_lock(monkeypatch)
    a, b = staged(world.engine, gate, lambda: run_purge(world), lambda: world.restore("pf", pf))
    counts, restore = assert_clean(a, b)  # no DeadlockDetected in either thread
    assert restore.status_code == 404  # waited for the purge, which removed the holding
    assert counts["pf"] == 1 and counts["stock"] == 1 and counts["cash"] == 1
    assert counts["exits"] == 1 and counts["fundings"] == 1
    assert world.holding("pf_holdings", pf) is None
    assert world.holding("stocks", stock) is None and world.holding("cash_holdings", cash) is None
    assert world.fundings() == [] and world.exits() == []
    check_invariants(world, ledger=False)


def test_restore_wins_then_purge_keeps_the_restored_holding(world):
    cash, stock, pf = chain_world(world)
    # The account is purge-eligible too, but a restore needs it live: bring it back first.
    assert world.restore("cash", cash).status_code == 200
    assert world.restore("pf", pf).status_code == 200
    counts = run_purge(world)
    assert counts["pf"] == 0 and counts["cash"] == 0 and counts["stock"] == 1
    assert world.holding("pf_holdings", pf).deleted_at is None
    (funding,) = world.fundings()
    assert funding.refunded_at is None
    assert world.balance(cash) == Decimal("8000") + 1000 - 5000
    check_invariants(world, ledger=False)


def test_lock_timeout_fails_cleanly_deletes_nothing_and_a_later_run_succeeds(world, monkeypatch):
    stock = world.add("stock", STOCK)
    pf = world.add("pf", PF)
    assert world.delete("stock", stock).status_code == 200
    assert world.delete("pf", pf).status_code == 200
    age(world, "stocks", "pf_holdings")
    monkeypatch.setattr(purge, "PURGE_LOCK_TIMEOUT", "500ms")
    with world.session() as blocker:
        blocker.execute(
            text("SELECT id FROM pf_holdings WHERE id = :i FOR UPDATE"), {"i": pf}
        ).all()  # held until this session ends
        with pytest.raises(purge.PurgeLockTimeout):
            run_purge(world)
        # All or nothing: the stock (locked before the pf) was not deleted either.
        assert world.holding("stocks", stock) is not None
        assert world.holding("pf_holdings", pf) is not None
        blocker.rollback()
    counts = run_purge(world)
    assert counts["stock"] == 1 and counts["pf"] == 1
    assert world.holding("stocks", stock) is None and world.holding("pf_holdings", pf) is None


def test_cron_endpoint_answers_503_with_a_message_on_a_lock_timeout(world, monkeypatch):
    pf = world.add("pf", PF)
    assert world.delete("pf", pf).status_code == 200
    age(world, "pf_holdings")
    monkeypatch.setattr(purge, "PURGE_LOCK_TIMEOUT", "500ms")
    monkeypatch.setattr(settings, "cron_secret", "cron-test-secret")
    headers = {"Authorization": "Bearer cron-test-secret"}
    with world.session() as blocker:
        blocker.execute(text("SELECT id FROM pf_holdings WHERE id = :i FOR UPDATE"), {"i": pf}).all()
        busy = world.app.client.get("/api/cron/purge", headers=headers)
        blocker.rollback()
    assert busy.status_code == 503
    assert busy.json()["message"] == purge.PurgeLockTimeout.message
    assert world.holding("pf_holdings", pf) is not None
    ok = world.app.client.get("/api/cron/purge", headers=headers)
    assert ok.status_code == 200 and ok.json()["pf"] == 1
