"""Helpers for the real-Postgres concurrency tests (test_concurrency_pg.py).

How an overlap is forced (a barrier before two HTTP calls does NOT make them overlap):
  1. A runs in a thread and is HELD inside its lock: a hook (`hold_after` wraps a module-level
     service function that runs after the row lock is taken; `hold_before_commit` is a Session
     event for paths with no such function) blocks A on a threading.Event while its transaction
     still holds every FOR UPDATE lock it took.
  2. B starts only after A is held, and `staged` polls pg_stat_activity/pg_locks until B is
     observed WAITING on a lock (`wait_for_lock_wait` fails the test when B never blocks, which
     proves the lock exists). Where B legitimately does not block (it filters the row out by state,
     e.g. delete vs restore) `expect_block=False` is passed explicitly.
  3. A is released, both threads are joined with a 20 s timeout (a deadlock fails fast).
There is no sleep and no pg_sleep. Every request builds its own TestClient, and TestClient re-raises
server exceptions, so a DeadlockDetected or lock_timeout error shows up as `Outcome.error`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from tests.pg.conftest import Outcome, make_user_token, wait_for_lock_wait

TIMEOUT = 20.0

# --- request bodies -----------------------------------------------------------------------------

STOCK = {
    "name": "Acme Ltd", "exchange": "NSE", "quantity": 100, "avg_buy_price": 50,
    "buy_date": "2025-01-01",
}  # fmt: skip
FD = {
    "bank": "Old Bank", "principal": 100000, "rate": 8, "start_date": "2024-01-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
FUND = {
    "scheme_name": "Fund A", "scheme_code": 100, "platform": "Groww", "category": "equity",
    "units": 100, "avg_nav": 40, "invested_amount": 4000, "purchase_date": "2025-06-01",
}  # fmt: skip
NONE = {"kind": "none"}
SELL_DAY = "2026-01-15"
TODAY = date(2026, 3, 10)  # "today" for post_due (passed explicitly)


def cash_body(name: str = "HDFC Savings", balance: float = 100000) -> dict:
    return {"name": name, "kind": "savings", "balance": balance, "balance_date": "2026-01-01"}


def stock_body(name: str = "Acme Ltd", quantity: int = 100) -> dict:
    return {**STOCK, "name": name, "quantity": quantity}


# --- holds --------------------------------------------------------------------------------------


class Gate:
    """`entered` is set when A is held inside its lock; `release` lets it go."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def hold(self) -> None:
        self.entered.set()
        if not self.release.wait(TIMEOUT):
            raise RuntimeError("gate was never released")


def hold_after(
    monkeypatch, module, name: str, predicate: Callable[[tuple, dict], bool] | None = None
) -> Gate:
    """Wrap `module.name`: the FIRST matching call runs, then blocks (locks still held)."""
    original = getattr(module, name)
    gate = Gate()
    state = {"taken": False}
    guard = threading.Lock()

    def wrapper(*args, **kwargs):
        mine = False
        if predicate is None or predicate(args, kwargs):
            with guard:
                if not state["taken"]:
                    state["taken"] = True
                    mine = True
        if not mine:
            return original(*args, **kwargs)
        try:
            result = original(*args, **kwargs)
        except BaseException:
            gate.entered.set()
            raise
        gate.hold()
        return result

    monkeypatch.setattr(module, name, wrapper)
    return gate


@contextmanager
def hold_before_commit(target, predicate: Callable[[Any], bool]):
    """Hold the first commit of a session (of the sessionmaker `target`) matching `predicate`.

    before_commit runs while the transaction still holds its row locks and before the flush, so the
    SELECT ... FOR UPDATE locks of the request are in place; `session.dirty/new` show its changes.
    """
    gate = Gate()
    state = {"taken": False}
    guard = threading.Lock()

    def listener(session):
        if not predicate(session):
            return
        with guard:
            if state["taken"]:
                return
            state["taken"] = True
        gate.hold()

    event.listen(target, "before_commit", listener)
    try:
        yield gate
    finally:
        gate.release.set()
        event.remove(target, "before_commit", listener)


# --- running a pair -----------------------------------------------------------------------------


def _thread(func: Callable[[], Any], name: str) -> tuple[threading.Thread, Outcome]:
    outcome = Outcome()

    def run() -> None:
        try:
            outcome.value = func()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcome.error = exc

    thread = threading.Thread(target=run, daemon=True, name=name)
    thread.start()
    return thread, outcome


def staged(
    engine, gate: Gate, first: Callable[[], Any], second: Callable[[], Any], *,
    expect_block: bool = True,
) -> tuple[Outcome, Outcome]:  # fmt: skip
    """Hold `first` inside its lock, start `second`, see it wait, release, join both.

    Fails the test when `first` never reaches its hold, when `second` never waits on a lock
    (unless expect_block=False) or when either thread is still running after 20 s (deadlock).
    """
    thread_a, out_a = _thread(first, "pg-first")
    threads = [thread_a]
    try:
        deadline = time.monotonic() + 10
        while not gate.entered.wait(0.05):
            if not thread_a.is_alive() or time.monotonic() > deadline:
                pytest.fail(f"first call never reached its hold; outcome: {out_a.error!r} {out_a.value!r}")
        thread_b, out_b = _thread(second, "pg-second")
        threads.append(thread_b)
        if expect_block:
            wait_for_lock_wait(engine)
        else:
            # Let B finish on its own (it does not need A), then release A.
            thread_b.join(TIMEOUT)
    finally:
        gate.release.set()
    end = time.monotonic() + TIMEOUT
    for thread in threads:
        thread.join(max(0.0, end - time.monotonic()))
    stuck = [t.name for t in threads if t.is_alive()]
    if stuck:
        pytest.fail(f"still running after {TIMEOUT}s (deadlock or hang): {stuck}")
    return out_a, out_b


def assert_clean(*outcomes: Outcome) -> list[Any]:
    """No thread raised (no DeadlockDetected, lock_timeout or other server error); the values."""
    for outcome in outcomes:
        assert outcome.ok, repr(outcome.error)
    return [outcome.value for outcome in outcomes]


def statuses(*responses) -> list[int]:
    return [r.status_code for r in responses]


# --- the world of one test ----------------------------------------------------------------------


class World:
    """One user on the test database plus request and query helpers (all data is committed)."""

    def __init__(self, pg_app) -> None:
        self.app = pg_app
        self.engine = pg_app.engine
        self.session = pg_app.session
        with self.session() as s:
            self.user, self.headers = make_user_token(s)
        self.initial_cash: dict[int, Decimal] = {}

    # requests ------------------------------------------------------------------------------
    def call(self, method: str, url: str, **kwargs):
        from app.main import app

        return TestClient(app).request(method, url, headers=self.headers, **kwargs)

    def add(self, slug: str, body: dict, **query) -> int:
        r = self.call("POST", f"/api/assets/{slug}", json=body, params=query or None)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def add_cash(self, name: str = "HDFC Savings", balance: float = 100000) -> int:
        cash_id = self.add("cash", cash_body(name, balance))
        self.initial_cash[cash_id] = Decimal(str(balance))
        return cash_id

    def add_paid(self, slug: str, body: dict, cash_id: int, **paid):
        return self.call("POST", f"/api/assets/{slug}", json={**body, "paid_from": {"cash_id": cash_id, **paid}})

    def sell(self, slug: str, item_id: int, destination: dict | None = None, **fields):
        body = {"date": SELL_DAY, "destination": destination or NONE, **fields}
        return self.call("POST", f"/api/holdings/{slug}/{item_id}/sell", json=body)

    def sell_stock(self, item_id: int, quantity: int = 100, price: int = 80, to_cash: int | None = None):
        dest = {"kind": "cash_existing", "cash_id": to_cash} if to_cash else NONE
        return self.sell("stock", item_id, dest, quantity=quantity, price=price)

    def settle(self, slug: str, item_id: int, destination: dict | None = None):
        return self.call(
            "POST", f"/api/holdings/{slug}/{item_id}/settle", json={"destination": destination or NONE}
        )

    def undo(self, exit_id: int):
        return self.call("DELETE", f"/api/exits/{exit_id}")

    def delete(self, slug: str, item_id: int):
        return self.call("DELETE", f"/api/assets/{slug}/{item_id}")

    def restore(self, slug: str, item_id: int):
        return self.call("POST", f"/api/assets/{slug}/{item_id}/restore")

    def put(self, slug: str, item_id: int, body: dict):
        return self.call("PUT", f"/api/assets/{slug}/{item_id}", json=body)

    # queries (raw SQL: soft-deleted rows included) --------------------------------------------
    def rows(self, sql: str, **params) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(text(sql), params).all())

    def scalar(self, sql: str, **params) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def balance(self, cash_id: int) -> Decimal:
        return self.scalar("SELECT balance FROM cash_holdings WHERE id = :i", i=cash_id)

    def exits(self, slug: str | None = None, holding_id: int | None = None) -> list[Any]:
        return self.rows(
            "SELECT * FROM holding_exits WHERE (CAST(:s AS text) IS NULL OR asset_type = :s) "
            "AND (CAST(:h AS integer) IS NULL OR holding_id = :h) ORDER BY id",
            s=slug, h=holding_id,
        )

    def fundings(self) -> list[Any]:
        return self.rows("SELECT * FROM holding_fundings ORDER BY id")

    def holding(self, table: str, item_id: int) -> Any:
        rows = self.rows(f"SELECT * FROM {table} WHERE id = :i", i=item_id)  # noqa: S608 - test constant
        return rows[0] if rows else None

    def count(self, table: str) -> int:
        return self.scalar(f"SELECT count(*) FROM {table}")  # noqa: S608 - test constant

    # market data for SIP tests -----------------------------------------------------------------
    def seed_funds(self) -> None:
        """MF master 100, daily NAVs (50) from 2025-12-01 to 2026-04-30 and a fresh history sync
        (first_date <= every due date, fetched just now) so no NAV fetch is attempted."""
        from app.models import MFMaster, MFNavHistory, MFNavHistorySync

        with self.session() as s:
            s.add(MFMaster(scheme_code=100, name="Fund A - Direct Growth", category="equity", is_active=True))
            s.flush()
            day = date(2025, 12, 1)
            rows = []
            while day <= date(2026, 4, 30):
                rows.append(MFNavHistory(scheme_code=100, nav_date=day, nav=Decimal("50")))
                day += timedelta(days=1)
            s.add_all(rows)
            s.add(
                MFNavHistorySync(
                    scheme_code=100, first_date=date(2025, 12, 1), last_date=date(2026, 4, 30),
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            s.commit()

    def add_sip(self, fund_id: int | None, last_posted_on: date | None = None) -> int:
        """A monthly Rs 5,000 SIP on the 5th from 2026-01-05, inserted directly (nothing posted)."""
        from app.models import MfSip

        with self.session() as s:
            sip = MfSip(
                user_id=self.user.id, mutual_fund_id=fund_id, scheme_code=100, platform="Groww",
                amount=Decimal("5000"), day_of_month=5, start_date=date(2026, 1, 5),
                post_from=date(2026, 1, 5), status="active", last_posted_on=last_posted_on,
            )
            s.add(sip)
            s.commit()
            return sip.id

    def post_due(self) -> dict[int, int]:
        """post_due on its own session (as the nightly job does); {sip_id: instalments added}."""
        from app.services import sip as sip_service

        with self.session() as s:
            return sip_service.post_due(s, TODAY)

    def mf_net_units(self, fund_id: int) -> Decimal:
        return Decimal(
            self.scalar(
                "SELECT COALESCE(SUM(CASE WHEN kind = 'purchase' THEN units ELSE -units END), 0) "
                "FROM mf_transactions WHERE mutual_fund_id = :i",
                i=fund_id,
            )
        )


# --- invariants ---------------------------------------------------------------------------------

HOLDING_TABLES = {
    "fd": "fixed_deposits", "rd": "recurring_deposits", "stock": "stocks", "bond": "bonds",
    "mf": "mutual_funds", "nps": "nps_holdings", "gold": "gold_holdings",
    "cash": "cash_holdings", "pf": "pf_holdings", "other": "other_holdings",
}  # fmt: skip


def check_invariants(world: World, *, ledger: bool = True) -> None:
    """Money and integrity invariants on committed data.

    * no negative cash balance
    * no exit or funding row points at a holding row that does not exist (any state)
    * a funding is active exactly while its holding is live (refund/restore stay in step)
    * a deposit/bond is settled at most once
    * `ledger`: each account in world.initial_cash holds initial + exit proceeds - active fundings
      (skip it for a test that edits a balance by hand)
    * a live fund with transactions holds exactly the units its transactions net to
    * no SIP is linked to a holding that does not exist
    """
    assert world.scalar("SELECT count(*) FROM cash_holdings WHERE balance < 0") == 0, "negative cash"

    for row in world.rows("SELECT id, asset_type, holding_id FROM holding_exits"):
        assert world.holding(HOLDING_TABLES[row.asset_type], row.holding_id) is not None, (
            f"orphaned exit {row.id}"
        )
    for row in world.fundings():
        holding = world.holding(HOLDING_TABLES[row.asset_type], row.holding_id)
        assert holding is not None, f"orphaned funding {row.id}"
        live = holding.deleted_at is None
        assert (row.refunded_at is None) == live, (
            f"funding {row.id}: refunded_at={row.refunded_at} but holding live={live}"
        )

    dup = world.scalar(
        "SELECT count(*) FROM (SELECT asset_type, holding_id FROM holding_exits "
        "WHERE kind = 'maturity' GROUP BY 1, 2 HAVING count(*) > 1) d"
    )
    assert dup == 0, "a holding was settled twice"

    if ledger:
        for cash_id, initial in world.initial_cash.items():
            added = world.scalar(
                "SELECT COALESCE(SUM(cash_added), 0) FROM holding_exits WHERE cash_holding_id = :i",
                i=cash_id,
            )
            taken = world.scalar(
                "SELECT COALESCE(SUM(amount), 0) FROM holding_fundings "
                "WHERE cash_holding_id = :i AND refunded_at IS NULL",
                i=cash_id,
            )
            expected = initial + Decimal(added) - Decimal(taken)
            assert world.balance(cash_id) == expected, (
                f"cash {cash_id}: balance {world.balance(cash_id)} != initial {initial} "
                f"+ exits {added} - fundings {taken}"
            )

    for fund in world.rows("SELECT id, units FROM mutual_funds WHERE deleted_at IS NULL AND closed_on IS NULL"):
        if world.scalar("SELECT count(*) FROM mf_transactions WHERE mutual_fund_id = :i", i=fund.id):
            assert world.mf_net_units(fund.id) == fund.units, f"fund {fund.id}: units != transactions"

    for sip in world.rows("SELECT id, mutual_fund_id FROM mf_sips WHERE mutual_fund_id IS NOT NULL"):
        assert world.holding("mutual_funds", sip.mutual_fund_id) is not None, f"SIP {sip.id} dangling"
