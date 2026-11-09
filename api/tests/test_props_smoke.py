import os
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

TWO_DP = Decimal("0.01")


@given(st.decimals(min_value=Decimal("-1e9"), max_value=Decimal("1e9"), allow_nan=False, allow_infinity=False))
def test_quantize_two_dp_is_idempotent(value):
    once = value.quantize(TWO_DP, rounding=ROUND_HALF_UP)
    assert once.quantize(TWO_DP, rounding=ROUND_HALF_UP) == once


@given(st.integers(min_value=0, max_value=10**9), st.data())
def test_left_plus_sold_equals_held(held, data):
    sold = data.draw(st.integers(min_value=0, max_value=held))
    assert (held - sold) + sold == held


def test_active_profile_matches_env():
    expected = os.environ.get("HYPOTHESIS_PROFILE", "dev")
    assert settings.get_current_profile_name() == expected
