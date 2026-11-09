import os

from hypothesis import settings


def register() -> None:
    settings.register_profile("dev", max_examples=50, deadline=None, derandomize=False)
    settings.register_profile("ci", max_examples=100, deadline=None, print_blob=True, database=None)
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))
