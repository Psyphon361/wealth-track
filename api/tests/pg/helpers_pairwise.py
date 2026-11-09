"""Engine for the pairwise concurrency tests (test_pairwise_pg.py).

One pair (A, B) is run three times, each on a freshly truncated database (ids restart, so the
runs are comparable): A then B, B then A (the two serial outcomes), and A/B concurrently with a
forced overlap (A held inside its critical section by an Event hook, B started and observed
waiting). The concurrent result must equal one of the serial results: the same pair of response
codes AND the same normalised final state of the same order.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import text

from tests.pg.conftest import truncate_all
from tests.pg.helpers_t3 import (
    Gate,
    World,
    assert_clean,
    check_invariants,
    hold_after,
    hold_before_commit,
    staged,
)

STATE_TABLES = (
    "fixed_deposits", "recurring_deposits", "stocks", "bonds", "mutual_funds", "nps_holdings",
    "gold_holdings", "cash_holdings", "pf_holdings", "other_holdings", "holding_exits",
    "holding_fundings", "mf_transactions", "mf_sips", "mf_sip_skips",
)  # fmt: skip
DROPPED_COLUMNS = {"created_at", "updated_at"}


@dataclass(frozen=True)
class After:
    """Hold A right after a module-level service call (its row locks are held)."""

    module: Any
    name: str
    predicate: Callable[[tuple, dict], bool] | None = None


@dataclass(frozen=True)
class BeforeCommit:
    """Hold A at its first commit that has changed a row (`target`: 'app' or 'world' sessions)."""

    target: str = "app"


@dataclass(frozen=True)
class Pair:
    name: str
    build: Callable[[World], Any]
    a: Callable[[World, Any], Any]
    b: Callable[[World, Any], Any]
    hold: After | BeforeCommit
    blocks: bool = True  # False: B shares no lock with A and finishes on its own
    ledger: bool = True  # False when a balance is edited by hand


def normalise_result(value: Any) -> Any:
    if hasattr(value, "status_code"):
        return value.status_code
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return repr(value)


def snapshot(world: World) -> dict[str, list[tuple]]:
    """Every row of the money tables; timestamps become present/absent, ids are kept."""
    state: dict[str, list[tuple]] = {}
    with world.engine.connect() as conn:
        for table in STATE_TABLES:
            result = conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))  # noqa: S608 - constant
            rows = []
            for row in result.mappings():
                items = []
                for key in sorted(row):
                    if key in DROPPED_COLUMNS:
                        continue
                    value = row[key]
                    if isinstance(value, datetime):
                        value = "set"
                    items.append((key, value))
                rows.append(tuple(items))
            state[table] = rows
    return state


def _fresh(pg_app) -> World:
    truncate_all(pg_app.engine)
    return World(pg_app)


def _serial(pg_app, pair: Pair, first: str) -> tuple[tuple, dict]:
    world = _fresh(pg_app)
    ctx = pair.build(world)
    actions = {"a": pair.a, "b": pair.b}
    codes = {}
    for key in (first, "b" if first == "a" else "a"):
        codes[key] = normalise_result(actions[key](world, ctx))
    return (codes["a"], codes["b"]), snapshot(world)


def run_pair(pg_app, monkeypatch, pair: Pair) -> None:
    serial_ab = _serial(pg_app, pair, "a")
    serial_ba = _serial(pg_app, pair, "b")

    world = _fresh(pg_app)
    ctx = pair.build(world)
    with ExitStack() as stack:
        gate: Gate
        if isinstance(pair.hold, After):
            gate = hold_after(monkeypatch, pair.hold.module, pair.hold.name, pair.hold.predicate)
        else:
            from app.db import SessionLocal

            if pair.hold.target == "app":
                target, changed = SessionLocal, lambda s: bool(s.dirty or s.new or s.deleted)
            else:
                target, changed = world.session, lambda s: True  # bulk deletes leave no dirty rows
            gate = stack.enter_context(hold_before_commit(target, changed))
        out_a, out_b = staged(
            world.engine, gate,
            lambda: pair.a(world, ctx),
            lambda: pair.b(world, ctx),
            expect_block=pair.blocks,
        )  # fmt: skip
    value_a, value_b = assert_clean(out_a, out_b)
    observed = ((normalise_result(value_a), normalise_result(value_b)), snapshot(world))
    if observed not in (serial_ab, serial_ba):
        pytest.fail(
            f"{pair.name}: concurrent outcome matches neither serial order\n"
            f"concurrent codes {observed[0]}\nA then B codes {serial_ab[0]}\nB then A codes {serial_ba[0]}\n"
            f"state equals A->B: {observed[1] == serial_ab[1]}, B->A: {observed[1] == serial_ba[1]}"
        )
    check_invariants(world, ledger=pair.ledger)
