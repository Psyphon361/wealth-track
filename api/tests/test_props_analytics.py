"""Property tests for the analytics, capital gains and net worth maths. Exits are SimpleNamespace
stand-ins like tests/test_analytics_returns*.py. No DB, no network."""

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from hypothesis import assume, given
from hypothesis import strategies as st

from app.services import analytics_returns as ar
from app.services import capital_gains as cg
from app.services import networth

D = Decimal
TODAY = date(2026, 11, 2)
START = date(2022, 1, 3)


def cents(n: int) -> Decimal:
    return D(n) / 100


def ex(day, amount, cost, quantity=None, full=False):
    return SimpleNamespace(
        exit_date=day, amount=amount, cost=cost, quantity=quantity,
        prev_state={"full": True} if full else {},
    )  # fmt: skip


@st.composite
def sale_history(draw):
    """Invested left on a fully sold holding plus its exits: partials, then one full sale."""
    n_partial = draw(st.integers(0, 4))
    day = START
    exits = []
    for _ in range(n_partial):
        day += timedelta(days=draw(st.integers(1, 120)))
        exits.append(ex(day, cents(draw(st.integers(1, 10**8))), cents(draw(st.integers(1, 10**8)))))
    day += timedelta(days=draw(st.integers(1, 120)))
    invested = cents(draw(st.integers(1, 10**8)))
    exits.append(ex(day, cents(draw(st.integers(1, 10**8))), invested, full=True))
    return invested, exits


@given(sale_history())
def test_original_cost_and_realised_gain_identities(h):
    invested, exits = h
    partial_cost = sum((e.cost for e in exits if not e.prev_state), D(0))
    assert ar.realised_gain(exits) == sum((e.amount - e.cost for e in exits), D(0))
    assert ar.original_cost("stock", {"invested": invested}, exits) == invested + partial_cost
    assert ar.original_cost("other", {"invested_amount": invested}, exits) == invested + partial_cost
    # the full-sale exit never double counts
    assert ar.original_cost("stock", {"invested": invested}, exits[-1:]) == invested
    assert ar.original_cost("stock", {"invested": invested}) == invested


@given(sale_history())
def test_a_sold_holdings_inflows_equal_the_exit_amounts(h):
    invested, exits = h
    item = {
        "status": "sold", "invested": invested, "current_value": D(0),
        "buy_date": START - timedelta(days=30), "price": None,
    }  # fmt: skip
    got = ar.holding_flows("stock", item, TODAY, exits=exits)
    assert got.reason is None
    inflows = sum((a for _, a in got.flows if a > 0), D(0))
    assert inflows == sum((e.amount for e in exits), D(0))
    outflows = sum((a for _, a in got.flows if a < 0), D(0))
    assert outflows == -ar.original_cost("stock", item, exits)
    assert got.flows == sorted(got.flows, key=lambda f: f[0])


# --- the rounding the Returns module really uses ------------------------------------------------------


def test_returns_q_rounds_half_even_while_the_rest_rounds_half_up():
    """PIN (finding): analytics_returns._q quantizes with the context default, ROUND_HALF_EVEN,
    but valuation._q and exits.money use ROUND_HALF_UP. Ties therefore disagree."""
    from app.services import exits, valuation

    assert ar._q(D("0.125")) == D("0.12")
    assert ar._q(D("0.135")) == D("0.14")
    assert ar._q(D("2.5")) == D("2.50")
    assert valuation._q(D("0.125")) == D("0.13")
    assert exits.money(D("0.125")) == D("0.13")
    assert ar._q(D("0.126")) == D("0.13")


# --- capital gains lot split -----------------------------------------------------------------------------


@st.composite
def mf_sales(draw):
    n = draw(st.integers(1, 6))
    day = date(2021, 1, 1)
    txns = []
    for i in range(n):
        day += timedelta(days=draw(st.integers(1, 120)))
        txns.append(
            cg.MfTxn(
                i + 1, day, "purchase",
                D(draw(st.integers(1, 10**7))) / 1000, cents(draw(st.integers(1, 10**9))),
            )
        )
    units = sum((t.units for t in txns), D(0))
    cost = cg.money(sum((t.amount for t in txns), D(0)))
    sold_on = day + timedelta(days=draw(st.integers(1, 800)))
    txns.append(cg.MfTxn(99, sold_on, "redemption", units, D(0)))
    proceeds = cents(draw(st.integers(0, 10**10)))
    return cg.SaleInput(
        exit_id=1, asset_type="mf", holding_id=1, name="f", sold_on=sold_on, quantity=units,
        proceeds=proceeds, cost=cost, bought_on=txns[0].txn_date, mf_category="equity",
        mf_txns=tuple(txns), mf_transaction_id=99,
    )  # fmt: skip


@given(mf_sales())
def test_split_lots_sums_exactly_to_proceeds_and_cost(sale):
    lots = cg.split_lots(sale)
    assert sum((lot["proceeds"] for lot in lots), D(0)) == cg.money(sale.proceeds)
    assert sum((lot["cost"] for lot in lots), D(0)) == cg.money(sale.cost)
    assert all(lot["quantity"] is not None for lot in lots)


@given(
    st.integers(0, 10**9),
    st.integers(0, 10**9),
    st.sampled_from(["stock", "bond", "gold"]),
)
def test_split_lots_single_lot_for_non_funds(proceeds, cost, kind):
    sale = cg.SaleInput(
        exit_id=1, asset_type=kind, holding_id=1, name="x", sold_on=TODAY, quantity=D(1),
        proceeds=cents(proceeds), cost=cents(cost), bought_on=START,
    )  # fmt: skip
    lots = cg.split_lots(sale)
    assert len(lots) == 1
    assert lots[0]["proceeds"] == cents(proceeds) and lots[0]["cost"] == cents(cost)


# --- networth.on_or_before ----------------------------------------------------------------------------------


@st.composite
def series_and_day(draw):
    days = sorted(draw(st.sets(st.integers(0, 3000), min_size=0, max_size=12)))
    series = [(START + timedelta(days=d), D(i)) for i, d in enumerate(days)]
    on = START + timedelta(days=draw(st.integers(-100, 3200)))
    return series, on


@given(series_and_day(), st.none() | st.integers(0, 400))
def test_on_or_before_returns_the_latest_entry_not_after_the_day(sd, max_age):
    series, on = sd
    got = networth.on_or_before(series, on, max_age)
    eligible = [(d, v) for d, v in series if d <= on]
    if not eligible:
        assert got is None
        return
    d, v = eligible[-1]
    if max_age is not None and (on - d).days > max_age:
        assert got is None
    else:
        assert got == v
    if max_age is None:
        assert got == v
    assume(True)
