"""The money-conservation state machine on real Postgres (small budget).

Same machine as tests/stateful (see tests/stateful/machine.py), run against the throwaway local
`wt_test_*` database of the `pg_app` fixture. It adds what SQLite cannot: foreign keys and their
ON DELETE actions, CHECK and partial unique indexes as Postgres enforces them, and Numeric
columns that come back as Decimal. Not included: concurrency (test_concurrency_pg.py) and the purge
(test_purge_hardening_pg.py); the machine has no purge rule.

Budget: 25 examples of up to 25 steps (STATEFUL_PG_EXAMPLES overrides it for a local hunt).
"""

import os

import pytest
from hypothesis import HealthCheck, Phase, settings
from hypothesis.stateful import run_state_machine_as_test

from tests.stateful.machine import TALLY, MoneyMachine, report_and_check_valid_share
from tests.stateful.world import pg_harness

pytestmark = pytest.mark.pg


def test_money_machine_pg(pg_app, monkeypatch):
    harness = pg_harness(pg_app, monkeypatch)
    TALLY.clear()
    config = settings(
        settings.default,
        max_examples=int(os.environ.get("STATEFUL_PG_EXAMPLES", "25")),
        stateful_step_count=int(os.environ.get("STATEFUL_PG_STEPS", "25")),
        deadline=None,
        phases=[Phase.explicit, Phase.reuse, Phase.generate]
        if os.environ.get("STATEFUL_NO_SHRINK") == "1"
        else tuple(Phase),
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much, HealthCheck.data_too_large],
    )
    run_state_machine_as_test(lambda: MoneyMachine(harness), settings=config)
    report_and_check_valid_share("postgres")
