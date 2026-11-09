"""Stateful money-conservation test on SQLite (no network, no real database).

Hypothesis drives random sequences of API calls (add cash and holdings, Paid From, sell, settle,
undo, reinvest, delete and restore of holdings and cash accounts, PUT of a balance, SIPs and the
clock) against the real app on an in-memory SQLite database, and checks the machine's own ledger
after every step (see tests/stateful/machine.py).

Known limits (by design):
  * SQLite does not enforce foreign keys here, so ON DELETE CASCADE / SET NULL are not exercised
    (tests/pg/test_money_machine_pg.py runs the same machine on Postgres).
  * No concurrency (tests/pg/test_concurrency_pg.py covers it) and no purge.
  * The clock is frozen to the harness date everywhere (tests/stateful/world.py), so the wall
    clock affects nothing.

Failures: a real bug found by the machine is reproduced as a deterministic plain test in
test_known_bugs.py (fixed ones stay as regression tests). Never commit @reproduce_failure.
"""

import os

import pytest
from hypothesis import HealthCheck, Phase, settings
from hypothesis.stateful import run_state_machine_as_test

from tests.stateful.machine import TALLY, MoneyMachine, report_and_check_valid_share
from tests.stateful.world import sqlite_harness


def machine_settings() -> settings:
    base = settings.default
    return settings(
        base,
        # capped at 50 examples; STATEFUL_EXAMPLES=N overrides it for a deeper local hunt
        max_examples=int(os.environ.get("STATEFUL_EXAMPLES", min(base.max_examples, 50))),
        stateful_step_count=int(os.environ.get("STATEFUL_STEPS", "60")),
        deadline=None,
        # STATEFUL_NO_SHRINK=1 skips shrinking (quick triage; shrinking can take minutes).
        phases=[Phase.explicit, Phase.reuse, Phase.generate]
        if os.environ.get("STATEFUL_NO_SHRINK") == "1"
        else tuple(Phase),
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large],
    )


def test_money_machine_sqlite(auth_settings, monkeypatch):
    TALLY.clear()
    with sqlite_harness(
        monkeypatch, foreign_keys=os.environ.get("STATEFUL_SQLITE_FK") == "1"
    ) as harness:
        run_state_machine_as_test(lambda: MoneyMachine(harness), settings=machine_settings())
    report_and_check_valid_share("sqlite")
