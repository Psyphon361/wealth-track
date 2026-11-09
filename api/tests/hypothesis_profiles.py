"""Hypothesis profiles (select with HYPOTHESIS_PROFILE=dev|ci|hunt; default dev).

  dev   50 examples, random each run. Quick local runs.
  ci    100 examples, DERANDOMIZED: CI explores the same examples every run, so a green push can't
        turn red on random luck. print_blob=True, no example database.
  hunt  300 examples, random each run, no example database. For exploratory local runs:
            HYPOTHESIS_PROFILE=hunt .venv/bin/python -m pytest -q tests/stateful
        add --hypothesis-seed=N to repeat a run. A nightly job can use hunt with random seeds;
        a failure there is a finding, to be reproduced as a deterministic test.
"""

import os

from hypothesis import settings


def register() -> None:
    settings.register_profile("dev", max_examples=50, deadline=None, derandomize=False)
    settings.register_profile(
        "ci", max_examples=100, deadline=None, print_blob=True, database=None, derandomize=True
    )
    settings.register_profile(
        "hunt", max_examples=300, deadline=None, derandomize=False, database=None, print_blob=True
    )
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
