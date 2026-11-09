"""Property tests for the pure SIP maths in services/sip.py. No DB, no network."""

from datetime import date, timedelta
from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from app.services import sip

D = Decimal
dates_st = st.dates(min_value=date(2015, 1, 1), max_value=date(2035, 12, 31))
dom_st = st.integers(1, 28)


@given(st.integers(100, 10**8).map(lambda c: D(c) / 100), st.integers(1000, 10**7).map(lambda n: D(n) / 10000))
def test_units_for_is_the_stamp_duty_formula_to_three_dp(amount, nav):
    got = sip.units_for(amount, nav)
    exact = amount * D("0.99995") / nav
    assert abs(got - exact) <= D("0.0005")
    assert got == got.quantize(D("0.001"))
    if exact >= D("0.0005"):
        assert got > 0


@given(dom_st, dates_st)
def test_first_due_is_on_or_after_and_on_the_day(dom, on):
    due = sip.first_due_on_or_after(dom, on)
    assert due >= on and due.day == dom
    assert due - on < timedelta(days=32)
    # nothing earlier qualifies
    assert not (on <= due - timedelta(days=1) and (due - timedelta(days=1)).day == dom)


@given(
    dom_st,
    dates_st,
    st.integers(0, 1500),
    st.lists(st.integers(0, 40), max_size=5),
)
def test_due_dates_strictly_increasing_inside_the_window(dom, start, span, skip_idx):
    until = start + timedelta(days=span)
    everything = sip.due_dates(dom, start, until)
    assert all(d.day == dom and start <= d <= until for d in everything)
    assert all(a < b for a, b in zip(everything, everything[1:]))
    assert all((b.year, b.month) > (a.year, a.month) for a, b in zip(everything, everything[1:]))
    skipped = {everything[i] for i in skip_idx if i < len(everything)}
    assert sip.due_dates(dom, start, until, skipped=skipped) == [d for d in everything if d not in skipped]


@given(dom_st, dates_st, st.integers(0, 1500), st.integers(0, 1500))
def test_due_dates_after_and_end_date(dom, start, span, end_off):
    until = start + timedelta(days=span)
    end = start + timedelta(days=end_off)
    full = sip.due_dates(dom, start, until, end_date=end)
    assert all(d <= end for d in full)
    if full:
        rest = sip.due_dates(dom, start, until, end_date=end, after=full[0])
        assert rest == full[1:]


@given(dom_st, dates_st, dates_st, st.none() | dates_st)
def test_next_due_is_after_the_last_posted_and_not_before_today(dom, today, post_from, last):
    got = sip.next_due(dom, today, post_from, last_posted_on=last)
    assert got is not None and got.day == dom
    assert got >= max(today, post_from)
    if last is not None:
        assert got > last


@given(dom_st, dates_st, dates_st)
def test_next_due_respects_the_end_date(dom, today, post_from):
    free = sip.next_due(dom, today, post_from)
    assert sip.next_due(dom, today, post_from, end_date=free) == free
    assume(free > date(2015, 1, 2))
    assert sip.next_due(dom, today, post_from, end_date=free - timedelta(days=1)) is None


@given(dom_st, dates_st, st.integers(1, 1500))
def test_next_due_agrees_with_due_dates(dom, today, span):
    until = today + timedelta(days=span)
    dues = sip.due_dates(dom, today, until)
    assume(dues)
    assert sip.next_due(dom, today, today) == dues[0]
