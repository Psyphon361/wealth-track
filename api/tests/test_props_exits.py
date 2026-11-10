"""Property tests for the pure closing maths in services/exits.py. Money is built from integer
cents, units from thousandths; no DB, no network."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.services import exits
from app.services.exits import ExitRefused

D = Decimal
CENT = D("0.01")


def cents(n: int) -> Decimal:
    return D(n) / 100


def thou(n: int) -> Decimal:
    return D(n) / 1000


invested_st = st.integers(min_value=0, max_value=10**10).map(cents)  # up to 100 crore
held_st = st.integers(min_value=1, max_value=10**8).map(thou)
SLUGS = st.sampled_from(["stock", "mf", "bond", "gold"])


@st.composite
def held_and_parts(draw, parts=2):
    """held units and `parts` positive thousandth-sized quantities that sum to <= held."""
    total = draw(st.integers(min_value=parts, max_value=10**8))
    cuts = sorted(draw(st.lists(st.integers(1, total - 1), min_size=parts - 1, max_size=parts - 1, unique=True))) if parts > 1 else []
    edges = [0, *cuts, total]
    sizes = [thou(b - a) for a, b in zip(edges, edges[1:])]
    return thou(total), sizes


# --- proportional_cost ----------------------------------------------------------------------


@given(invested_st, held_and_parts(parts=2))
def test_proportional_cost_bounds_and_monotone(invested, hp):
    held, (a, b) = hp
    ca = exits.proportional_cost(invested, held, a)
    cab = exits.proportional_cost(invested, held, a + b)
    assert 0 <= ca <= cab <= invested
    assert exits.proportional_cost(invested, held, held) == exits.money(invested)
    assert exits.proportional_cost(invested, held, D(0)) == 0


@given(invested_st, held_and_parts(parts=3))
def test_two_partials_equal_full_within_a_paisa(invested, hp):
    held, (a, b, _rest) = hp
    split = exits.proportional_cost(invested, held, a) + exits.proportional_cost(invested, held, b)
    whole = exits.proportional_cost(invested, held, a + b)
    assert abs(split - whole) <= CENT


@given(invested_st)
def test_proportional_cost_no_holding(invested):
    assert exits.proportional_cost(invested, D(0), D(1)) == 0


# --- partials followed by the final full sale ---------------------------------------------------


@given(
    st.integers(min_value=1, max_value=10**10).map(cents),
    held_and_parts(parts=4),
    st.sampled_from(["stock", "mf"]),
)
def test_partials_then_full_sale_sum_to_invested_exactly(invested, hp, slug):
    held, sizes = hp
    cur_held, cur_inv, total_cost = held, invested, D(0)
    for qty in sizes[:-1]:
        cost = exits.sale_cost(slug, held=cur_held, invested=cur_inv, quantity=qty, full=False)
        assert 0 <= cost <= cur_inv
        left, left_inv, _ = exits.remaining_after(slug, cur_held, cur_inv, qty, cost)
        assert left + qty == cur_held
        assert left_inv == cur_inv - cost >= 0
        total_cost += cost
        cur_held, cur_inv = left, left_inv
    final = exits.sale_cost(slug, held=cur_held, invested=cur_inv, quantity=cur_held, full=True)
    assert total_cost + final == invested


# --- net / gross ---------------------------------------------------------------------------------


@given(held_st, st.integers(0, 10**8).map(cents), st.integers(0, 10**7).map(cents))
def test_net_is_gross_less_charges_at_two_dp(qty, price, charges):
    gross = exits.gross_amount(qty, price)
    net = exits.net_amount(qty, price, charges)
    assert net == gross - charges
    assert gross == gross.quantize(CENT) and net.as_tuple().exponent == -2
    assert gross == (qty * price).quantize(CENT, rounding="ROUND_HALF_UP")


# --- fifo_cost -------------------------------------------------------------------------------------


def _txn(day, kind, units, amount, id_=0):
    return SimpleNamespace(id=id_, txn_date=day, kind=kind, units=units, amount=amount)


@st.composite
def purchases(draw):
    n = draw(st.integers(1, 6))
    day = date(2020, 1, 1)
    out = []
    for i in range(n):
        day += timedelta(days=draw(st.integers(1, 90)))
        u = thou(draw(st.integers(1, 10**7)))
        amt = cents(draw(st.integers(1, 10**9)))
        out.append(_txn(day, "purchase", u, amt, i))
    return out


@given(purchases())
def test_fifo_selling_everything_costs_everything(txns):
    total_units = sum((t.units for t in txns), D(0))
    total_cost = sum((t.amount for t in txns), D(0))
    assert exits.fifo_cost(txns, total_units) == exits.money(total_cost)


@given(purchases(), st.data())
def test_fifo_cost_bounded_and_monotone(txns, data):
    total_units = sum((t.units for t in txns), D(0))
    total_cost = sum((t.amount for t in txns), D(0))
    a = thou(data.draw(st.integers(0, int(total_units * 1000))))
    b = thou(data.draw(st.integers(int(a * 1000), int(total_units * 1000))))
    ca, cb = exits.fifo_cost(txns, a), exits.fifo_cost(txns, b)
    assert 0 <= ca <= cb <= exits.money(total_cost)


@given(purchases(), st.data())
def test_fifo_consumes_exactly_the_sold_units(txns, data):
    """Selling q1, then q2 on top of that redemption, costs what selling q1 + q2 at once costs."""
    total = int(sum((t.units for t in txns), D(0)) * 1000)
    q1 = data.draw(st.integers(1, total))
    q2 = data.draw(st.integers(0, total - q1))
    after = [*txns, _txn(date(2030, 1, 1), "redemption", thou(q1), D(0), 99)]
    split = exits.fifo_cost(txns, thou(q1)) + exits.fifo_cost(after, thou(q2))
    assert abs(split - exits.fifo_cost(txns, thou(q1 + q2))) <= D("0.02")


@given(purchases(), st.integers(0, 5000))
def test_fifo_short_only_beyond_tolerance(txns, extra):
    total = sum((t.units for t in txns), D(0))
    wanted = total + thou(extra)
    if extra <= 10:  # within the 0.01 unit tolerance
        assert exits.fifo_cost(txns, wanted) == exits.money(sum((t.amount for t in txns), D(0)))
    else:
        with pytest.raises(ValueError):
            exits.fifo_cost(txns, wanted)


# --- sale_cost -----------------------------------------------------------------------------------


@given(SLUGS, invested_st, held_and_parts(parts=2), st.booleans())
def test_sale_cost_never_exceeds_invested(slug, invested, hp, full):
    held, (qty, _) = hp
    cost = exits.sale_cost(slug, held=held, invested=invested, quantity=qty, full=full)
    assert 0 <= cost <= exits.money(invested)
    if full:
        assert cost == exits.money(invested)


@given(purchases(), st.data())
def test_sale_cost_of_a_fund_with_consistent_invested_is_fifo_and_capped(txns, data):
    held = sum((t.units for t in txns), D(0))
    lots_cost = exits.fifo_cost(txns, held)
    # invested within 1.00 of the cost of the units held
    invested = max(lots_cost + cents(data.draw(st.integers(-100, 100))), D(0))
    qty = thou(data.draw(st.integers(1, int(held * 1000))))
    cost = exits.sale_cost("mf", held=held, invested=invested, quantity=qty, full=False, txns=txns)
    assert 0 <= cost <= exits.money(invested)
    assert cost == min(exits.fifo_cost(txns, qty), exits.money(invested))


@given(purchases(), st.data())
def test_sale_cost_of_an_edited_fund_is_pro_rata_and_capped(txns, data):
    held = sum((t.units for t in txns), D(0))
    lots_cost = exits.fifo_cost(txns, held)
    gap = cents(data.draw(st.integers(101, 10**9)))  # more than 1.00 away
    invested = lots_cost + gap if data.draw(st.booleans()) else max(lots_cost - gap, D(0))
    if abs(invested - lots_cost) <= D("1.00"):  # clipped at zero for a cheap fund
        return
    qty = thou(data.draw(st.integers(1, int(held * 1000))))
    cost = exits.sale_cost("mf", held=held, invested=invested, quantity=qty, full=False, txns=txns)
    assert cost == min(exits.proportional_cost(invested, held, qty), exits.money(invested))


@given(purchases(), st.integers(1, 6), st.data())
def test_chain_of_partial_sales_on_an_unedited_fund_stays_fifo_and_sums_exactly(txns, steps, data):
    """Rounding drift after each sale never flips the branch; costs telescope to the purchases."""
    txns = list(txns)
    held = sum((t.units for t in txns), D(0))
    invested = sum((t.amount for t in txns), D(0))
    total_cost = invested
    day = date(2030, 1, 1)
    costs = []
    for i in range(steps):
        if held <= thou(1):
            break
        qty = thou(data.draw(st.integers(1, int(held * 1000) - 1)))
        assert exits.invested_matches_lots(txns, held, invested)
        cost = exits.sale_cost(
            "mf", held=held, invested=invested, quantity=qty, full=False, txns=txns
        )
        assert cost == min(exits.fifo_cost(txns, qty), exits.money(invested))
        costs.append(cost)
        held, invested, _ = exits.remaining_after("mf", held, invested, qty, cost)
        day += timedelta(days=1)
        txns.append(_txn(day, "redemption", qty, D(1), 100 + i))
    final = exits.sale_cost("mf", held=held, invested=invested, quantity=held, full=True, txns=txns)
    assert sum(costs, D(0)) + final == total_cost


# --- remaining_after / remainder floor ----------------------------------------------------------------


@given(SLUGS, invested_st, held_and_parts(parts=2), st.data())
def test_remaining_after_conserves_units_and_money(slug, invested, hp, data):
    held, (qty, rest) = hp
    cost = cents(data.draw(st.integers(0, int(invested * 100))))
    left, left_inv, avg = exits.remaining_after(slug, held, invested, qty, cost)
    assert left + qty == held
    assert left_inv == invested - cost >= 0
    assert (avg is not None) == (slug == "mf" and left > 0)


def _floor_paise(left_thousandths: int) -> int:
    return max(-(-(left_thousandths * 5) // 10**6), 1)  # ceil(left * 0.00005 * 100), at least 1


@given(
    st.sampled_from(["mf", "stock"]),
    st.integers(1, 10**9),
    st.integers(0, 3),
    st.integers(0, 10**9),
)
def test_check_remainder_accepts_iff_at_or_above_the_floor(slug, left_k, delta_kind, extra):
    floor = _floor_paise(left_k) if slug == "mf" else 1
    # remainder exactly at the floor, one paisa below, one above, or anywhere
    left_inv_paise = [floor, floor - 1, floor + 1, extra % (2 * floor + 2)][delta_kind]
    left_inv = cents(left_inv_paise)
    cost = cents(extra)
    held = thou(left_k) + D(3)
    invested = left_inv + cost
    assert exits.remainder_floor(slug, thou(left_k)) == cents(floor)
    if left_inv_paise >= floor:
        exits.check_remainder(slug, held, invested, D(3), cost)
    else:
        with pytest.raises(ExitRefused):
            exits.check_remainder(slug, held, invested, D(3), cost)


@given(st.integers(1, 10**9))
def test_mf_floor_rounds_up_to_the_paisa(left_k):
    floor = exits.remainder_floor("mf", thou(left_k))
    exact = D("0.00005") * thou(left_k)
    assert floor >= exact and floor - exact < CENT or floor == CENT
    assert floor >= CENT
