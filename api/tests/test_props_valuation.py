"""Property tests for valuation.xirr and value_fd. Pure maths; no DB, no network."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import assume, given
from hypothesis import strategies as st

from app.services import valuation
from app.services.valuation import xirr

D = Decimal
EPOCH = date(2012, 1, 1)


def cents(n: int) -> Decimal:
    return D(n) / 100


def ref_xirr(flows):
    """Independent bisection on NPV (same convention: Actual/365 from the earliest flow)."""
    first = min(d for d, _ in flows)
    pts = [((d - first).days / 365, float(a)) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in pts)

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(400):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def npv_at(flows, rate):
    first = min(d for d, _ in flows)
    return sum(float(a) / (1 + rate) ** ((d - first).days / 365) for d, a in flows)


# Rs 100 to 1 crore: the solver stops at an absolute |NPV| < 1e-9, so paisa-sized flows are not
# meaningful inputs (e.g. -0.01 then +0.01 a day later returns -1.2e-5, not 0).
def assert_root(flows, rate):
    """NPV is ~0 at `rate`, or (where NPV is very steep, rates near -100 %) the NPV changes sign
    within 1e-6 of it, i.e. `rate` is the root to the solver's own precision."""
    scale = sum(abs(float(a)) for _, a in flows)
    if abs(npv_at(flows, rate)) <= 1e-6 * scale:
        return
    lo, hi = npv_at(flows, rate - 1e-6), npv_at(flows, rate + 1e-6)
    assert lo * hi <= 0, (rate, lo, hi)


amount_st =st.integers(10**4, 10**9).map(cents)


@st.composite
def single_change_flows(draw):
    """Outflows on or before a pivot day, inflows strictly after it: one sign change in time."""
    pivot = EPOCH + timedelta(days=draw(st.integers(0, 4000)))
    outs = draw(st.lists(st.tuples(st.integers(-1500, 0), amount_st), min_size=1, max_size=4))
    ins = draw(st.lists(st.tuples(st.integers(1, 3000), amount_st), min_size=1, max_size=4))
    return [(pivot + timedelta(days=o), -a) for o, a in outs] + [
        (pivot + timedelta(days=i), a) for i, a in ins
    ]


@st.composite
def any_flows(draw):
    n = draw(st.integers(2, 8))
    return [
        (EPOCH + timedelta(days=draw(st.integers(0, 5000))),
         draw(st.sampled_from([-1, 1])) * draw(amount_st))
        for _ in range(n)
    ]  # fmt: skip


@given(single_change_flows())
def test_xirr_matches_the_reference_and_zeroes_the_npv(flows):
    rate = xirr(flows)
    ref = ref_xirr(flows)
    if rate is not None:
        assert_root(flows, float(rate))
        if ref is not None:
            assert abs(float(rate) - ref) <= 1e-6 * max(1.0, abs(ref))


@given(any_flows())
def test_xirr_npv_is_zero_whenever_a_rate_is_returned(flows):
    rate = xirr(flows)
    if rate is not None:
        assert_root(flows, float(rate))


@given(
    st.lists(
        st.tuples(st.integers(0, 5000), amount_st), min_size=2, max_size=8
    ),
    st.booleans(),
)
def test_no_sign_change_gives_none(rows, negative):
    sign = -1 if negative else 1
    flows = [(EPOCH + timedelta(days=d), sign * a) for d, a in rows]
    assert xirr(flows) is None


@given(any_flows(), st.integers(-3000, 3000))
def test_xirr_invariant_under_a_constant_day_shift(flows, shift):
    # a shift keeps every day difference, so the computation is identical
    shifted = [(d + timedelta(days=shift), a) for d, a in flows]
    assert xirr(shifted) == xirr(flows)


@given(single_change_flows(), st.randoms(use_true_random=False))
def test_xirr_order_invariant_single_root(flows, rnd):
    base = xirr(flows)
    shuffled = list(flows)
    rnd.shuffle(shuffled)
    other = xirr(shuffled)
    if base is not None and other is not None:
        assert abs(float(base) - float(other)) <= 1e-6 * max(1.0, abs(float(base)))


@given(single_change_flows(), amount_st)
def test_larger_terminal_inflow_gives_a_higher_rate(flows, extra):
    last = max(range(len(flows)), key=lambda i: (flows[i][0], flows[i][1]))
    bigger = list(flows)
    bigger[last] = (flows[last][0], flows[last][1] + extra)
    r1, r2 = xirr(flows), xirr(bigger)
    assume(r1 is not None and r2 is not None)
    assert float(r2) >= float(r1) - 1e-9


# --- value_fd ---------------------------------------------------------------------------------------


@st.composite
def fds(draw):
    return SimpleNamespace(
        principal=cents(draw(st.integers(1000, 10**9))),
        rate=D(draw(st.integers(0, 1500))) / 100,
        compounding=draw(st.sampled_from(["simple", "monthly", "quarterly", "half_yearly", "yearly"])),
        payout_type="cumulative",
        start_date=date(2018, 1, 1) + timedelta(days=draw(st.integers(0, 2000))),
        tenure_years=draw(st.integers(0, 5)),
        tenure_months=draw(st.integers(0, 11)),
        tenure_days=draw(st.integers(0, 30)),
    )


@given(fds(), st.integers(0, 4000), st.integers(0, 4000))
def test_value_fd_is_monotone_in_time_and_never_below_invested(fd, d1, d2):
    assume(fd.tenure_years + fd.tenure_months + fd.tenure_days > 0)
    t1, t2 = sorted((fd.start_date + timedelta(days=d1), fd.start_date + timedelta(days=d2)))
    a, b = valuation.value_fd(fd, t1), valuation.value_fd(fd, t2)
    assert a["current_value"] <= b["current_value"]
    for r in (a, b):
        assert r["current_value"] >= r["invested"]
        assert r["gain"] == r["current_value"] - r["invested"]


@given(fds(), st.integers(1, 300))
def test_value_fd_stops_growing_after_maturity(fd, extra):
    assume(fd.tenure_years + fd.tenure_months + fd.tenure_days > 0)
    maturity = valuation._maturity(fd)
    a = valuation.value_fd(fd, maturity)
    b = valuation.value_fd(fd, maturity + timedelta(days=extra))
    assert a["current_value"] == b["current_value"]
    assert b["status"] == "matured"
