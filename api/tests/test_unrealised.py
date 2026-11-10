"""Unrealised gains maths (services/unrealised.py): equivalence with the realised capital-gains
maths for a sale of each lot today, long_term_on, MF leftover lots, the exemption room and the
harvest lists. `today` is 2026-11-08."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services import capital_gains as cg
from app.services import unrealised as un
from app.services.capital_gains import MfTxn, SaleInput
from app.services.unrealised import HoldingInput

D = Decimal
TODAY = date(2026, 11, 8)


def holding(**kw):
    base = dict(
        asset_type="stock", holding_id=1, name="Acme", quantity=D(10), cost=D(1000),
        value=D(1500), bought_on=date(2025, 1, 1), stock_kind="stock",
    )  # fmt: skip
    base.update(kw)
    return HoldingInput(**base)


def txn(i, d, kind, units, amount):
    return MfTxn(i, d, kind, D(units), D(amount))


def realised_lot(h, lot, today=TODAY):
    """The realised-side lot for an actual sale of this unrealised lot today."""
    sale = SaleInput(
        exit_id=1, asset_type=h.asset_type, holding_id=h.holding_id, name=h.name, sold_on=today,
        quantity=lot["quantity"], proceeds=lot["value"], cost=lot["cost"], bought_on=lot["bought_on"],
        stock_kind=h.stock_kind, mf_category=h.mf_category, amfi_category=h.amfi_category,
        bond_type=h.bond_type, bond_has_master=h.bond_has_master, other_category=h.other_category,
    )  # fmt: skip
    return cg.build_sale(sale)


CASES = {
    "equity_stock": holding(),
    "equity_stock_short": holding(bought_on=date(2026, 6, 1)),
    "equity_fund": holding(asset_type="mf", mf_category="equity", stock_kind=None, bought_on=date(2024, 1, 1)),
    "debt_fund_before": holding(asset_type="mf", mf_category="debt", stock_kind=None, bought_on=date(2023, 3, 31)),
    "debt_fund_before_short": holding(asset_type="mf", mf_category="debt", stock_kind=None, bought_on=date(2025, 6, 1)),
    "debt_fund_after": holding(asset_type="mf", mf_category="debt", stock_kind=None, bought_on=date(2023, 4, 1)),
    "bond": holding(asset_type="bond", stock_kind=None, bought_on=date(2025, 1, 1)),
    "bond_short": holding(asset_type="bond", stock_kind=None, bought_on=date(2026, 3, 1)),
    "gold_long": holding(asset_type="gold", stock_kind=None, bought_on=date(2024, 6, 1)),
    "gold_short": holding(asset_type="gold", stock_kind=None, bought_on=date(2025, 1, 1)),
    "other": holding(asset_type="other", stock_kind=None, other_category="Property", bought_on=date(2020, 1, 1)),
    "crypto": holding(asset_type="other", stock_kind=None, other_category="Crypto", bought_on=None, value=D(700)),
    "no_date": holding(asset_type="other", stock_kind=None, other_category="Art", bought_on=None),
}  # fmt: skip


@pytest.mark.parametrize("name", CASES)
def test_single_lot_matches_realised_sale_today(name):
    h = CASES[name]
    built = un.build_holding(h, TODAY)
    [lot] = built["lots"]
    sale = realised_lot(h, lot)
    [real] = sale["lots"]
    assert lot["gain"] == real["gain"] == lot["value"] - lot["cost"]
    assert (lot["term"], lot["bucket"], lot["days_held"]) == (real["term"], real["bucket"], real["days_held"])
    for flag in sale["flags"]:
        assert flag in built["flags"]
    assert built["class"] == sale["class"]


PARTIAL_TXNS = [
    txn(1, date(2023, 1, 10), "purchase", 60, 2000),
    txn(2, date(2025, 6, 1), "purchase", 40, 2000),
    txn(3, date(2026, 1, 5), "redemption", 20, 1500),
]  # left: 40 units at 1333.33 and 40 units at 2000, FIFO cost 3333.33
PRORATA_TXNS = [
    txn(1, date(2023, 1, 10), "purchase", 70, 2100),
    txn(2, date(2025, 6, 1), "purchase", 30, 1500),
    txn(3, date(2026, 1, 5), "redemption", 25, 900),
    txn(4, date(2026, 2, 5), "redemption", 55, 2700),
]  # the second redemption takes the rest of lot 1 (45) and 10 of lot 2: left 20 units at 1000


def fund(txns, quantity, cost, value=D(5000)):
    return holding(
        asset_type="mf", mf_category="equity", stock_kind=None, quantity=D(quantity), cost=D(cost),
        value=D(value), bought_on=date(2025, 6, 1), mf_txns=txns,
    )  # fmt: skip


def real_full_redemption(h):
    """An actual redemption of the whole holding today, with the holding's invested amount as the
    exit cost (what exits.sale_cost gives)."""
    return cg.build_sale(
        SaleInput(
            exit_id=1, asset_type="mf", holding_id=1, name="F", sold_on=TODAY, quantity=h.quantity,
            proceeds=h.value, cost=h.cost, bought_on=h.bought_on, mf_category="equity",
            mf_txns=[*h.mf_txns, txn(9, TODAY, "redemption", h.quantity, h.value)], mf_transaction_id=9,
        )
    )  # fmt: skip


@pytest.mark.parametrize(
    "txns, quantity, cost, lots",
    [
        pytest.param(PARTIAL_TXNS, 80, 3333, 2, id="within_one_rupee_remainder_to_last_lot"),
        pytest.param(PARTIAL_TXNS, 80, 3334, 2, id="one_rupee_off_is_still_the_remainder_rule"),
        pytest.param(PARTIAL_TXNS, 80, 4500, 2, id="edited_invested_amount_scales_lot_costs"),
        pytest.param(PARTIAL_TXNS, 80, 2000, 2, id="edited_down_scales_lot_costs"),
        pytest.param(PRORATA_TXNS, 20, 1000, 1, id="pro_rata_partly_sold_fund"),
        pytest.param(PRORATA_TXNS, 20, 777.77, 1, id="pro_rata_partly_sold_fund_edited"),
    ],
)
def test_fund_lots_match_a_real_full_redemption_and_the_holding_gain(txns, quantity, cost, lots):
    h = fund(txns, quantity, D(str(cost)))
    built = un.build_holding(h, TODAY)
    real = real_full_redemption(h)
    assert len(built["lots"]) == len(real["lots"]) == lots
    for mine, theirs in zip(built["lots"], real["lots"], strict=True):
        assert mine["bought_on"] == theirs["bought_on"] and mine["quantity"] == theirs["quantity"]
        assert mine["cost"] == theirs["cost"] and mine["value"] == theirs["proceeds"]
        assert mine["gain"] == theirs["gain"]
        assert (mine["term"], mine["bucket"]) == (theirs["term"], theirs["bucket"])
        assert mine["cost"] >= 0
    # lots add up to the holding's invested amount, so every total agrees with the holding's gain
    assert sum(lot["cost"] for lot in built["lots"]) == h.cost
    assert sum(lot["value"] for lot in built["lots"]) == h.value
    assert built["gain"] == h.value - h.cost == sum(lot["gain"] for lot in built["lots"])
    assert "single_lot_fallback" not in built["flags"]
    report = un.build_report([built], 2026, TODAY, [])
    assert report["summary"]["total_gain"] == built["gain"]
    assert sum(b["net"] for b in report["buckets"]) == built["gain"]
    assert report["harvest"]["unrealised_equity_lt_gain"] == sum(
        lot["gain"] for lot in built["lots"] if lot["bucket"] == "equity_lt" and lot["gain"] > 0
    )
    assert sum(item["gain"] for item in report["harvest"]["loss_lots"]) == sum(
        lot["gain"] for lot in built["lots"] if lot["gain"] < 0
    )


THREE_EQUAL = [
    txn(1, date(2023, 1, 10), "purchase", 10, 1000),
    txn(2, date(2024, 6, 1), "purchase", 10, 1000),
    txn(3, date(2026, 5, 1), "purchase", 10, 1000),
]
THREE_UNEQUAL = [
    txn(1, date(2023, 1, 10), "purchase", 7, 700),
    txn(2, date(2024, 6, 1), "purchase", 13, 1500),
    txn(3, date(2026, 5, 1), "purchase", 11, 1200),
]


@pytest.mark.parametrize(
    "txns, quantity, cost, expected",
    [
        pytest.param(THREE_EQUAL, 30, 4500, ["33.33", "33.34", "33.33"], id="equal_lots_scaled_cumulative"),
        pytest.param(THREE_EQUAL, 30, 3000, ["33.33", "33.33", "33.34"], id="equal_lots_unscaled_remainder_last"),
        pytest.param(THREE_UNEQUAL, 31, 5000, None, id="unequal_lots_scaled_cumulative"),
    ],
)
def test_value_split_follows_the_realised_proceeds_rule(txns, quantity, cost, expected):
    h = fund(txns, quantity, D(str(cost)), value=D(100))
    built = un.build_holding(h, TODAY)
    real = real_full_redemption(h)
    values = [lot["value"] for lot in built["lots"]]
    assert values == [lot["proceeds"] for lot in real["lots"]]
    if expected is not None:
        assert values == [D(v) for v in expected]
    assert sum(values) == D(100)
    assert [lot["gain"] for lot in built["lots"]] == [lot["gain"] for lot in real["lots"]]
    assert [lot["bucket"] for lot in built["lots"]] == [lot["bucket"] for lot in real["lots"]]
    assert sum(lot["gain"] for lot in built["lots"]) == built["gain"] == D(100) - D(str(cost))


def test_scaled_costs_follow_the_fifo_weights():
    built = un.build_holding(fund(PARTIAL_TXNS, 80, 4000), TODAY)
    first, second = built["lots"]
    assert first["cost"] == D("1600.00") and second["cost"] == D("2400.00")  # 1333.33 : 2000 of 3333.33


def test_fund_whose_units_do_not_add_up_carries_the_fallback_flag():
    h = fund([txn(1, date(2024, 1, 1), "purchase", 50, 1000)], 80, 1000, 1500)
    assert "single_lot_fallback" in un.build_holding(h, TODAY)["flags"]
    # no transactions at all (a hand-entered fund) is an ordinary single lot
    assert "single_lot_fallback" not in un.build_holding(fund([], 80, 1000, 1500), TODAY)["flags"]


def test_leftover_lots_after_partial_redemption():
    txns = [
        txn(1, date(2024, 1, 1), "purchase", 100, 1000),
        txn(2, date(2024, 6, 1), "purchase", 50, 1000),
        txn(3, date(2025, 1, 1), "redemption", 120, 1500),
    ]
    assert cg.fifo_leftover_lots(txns) == [(date(2024, 6, 1), D(30), D(1000) * 30 / 50)]
    # the first lot is gone, the redemption took 20 of the second
    more = [*txns, txn(4, date(2025, 2, 1), "redemption", 30, 400)]
    assert cg.fifo_leftover_lots(more) == []


def test_leftover_follows_the_fifo_order_of_the_realised_side():
    # a purchase on the same day as a redemption counts first; ids break ties
    txns = [
        txn(5, date(2024, 1, 1), "redemption", 10, 100),
        txn(4, date(2024, 1, 1), "purchase", 10, 100),
        txn(2, date(2024, 3, 1), "purchase", 5, 60),
    ]
    assert cg.fifo_leftover_lots(txns) == [(date(2024, 3, 1), D(5), D(60))]
    # the lots a redemption consumed and the ones left add up to all purchases
    consumed = cg._fifo_lots([*txns, txn(6, date(2025, 1, 1), "redemption", 3, 30)], 6)
    left = cg.fifo_leftover_lots([*txns, txn(6, date(2025, 1, 1), "redemption", 3, 30)])
    assert sum(u for _, u, _ in consumed) + sum(u for _, u, _ in left) == D(5)


def test_fund_whose_lot_units_do_not_add_up_is_one_lot_at_the_purchase_date():
    txns = [txn(1, date(2024, 1, 1), "purchase", 50, 1000)]
    h = holding(
        asset_type="mf", mf_category="equity", stock_kind=None, quantity=D(80), mf_txns=txns,
        bought_on=date(2025, 3, 3),
    )  # fmt: skip
    [lot] = un.build_holding(h, TODAY)["lots"]
    assert (lot["bought_on"], lot["quantity"], lot["cost"], lot["value"]) == (date(2025, 3, 3), 80, 1000, 1500)
    assert un.build_holding(holding(asset_type="mf", mf_category="equity", stock_kind=None), TODAY)["lots"][0]["cost"] == 1000


def test_lot_values_sum_to_the_holding_value():
    txns = [txn(1, date(2024, 1, 1), "purchase", 3, 100), txn(2, date(2025, 1, 1), "purchase", 3, 100), txn(3, date(2025, 2, 1), "purchase", 4, 100)]
    h = holding(asset_type="mf", mf_category="equity", stock_kind=None, quantity=D(10), value=D(1000), mf_txns=txns)
    lots = un.build_holding(h, TODAY)["lots"]
    assert len(lots) == 3 and sum(lot["value"] for lot in lots) == 1000


def test_stock_is_one_average_lot_with_a_flag():
    built = un.build_holding(CASES["equity_stock"], TODAY)
    assert "single_lot_average" in built["flags"] and len(built["lots"]) == 1
    assert "single_lot_average" not in un.build_holding(CASES["gold_long"], TODAY)["flags"]


def test_estimated_flag_follows_the_input():
    assert "estimated" in un.build_holding(holding(asset_type="bond", estimated=True), TODAY)["flags"]


# --- long_term_on --------------------------------------------------------------------------


def test_long_term_on_is_the_day_after_the_months_and_matches_lot_bucket():
    for cls, bought in (
        ("equity", date(2026, 3, 15)),
        ("bond", date(2026, 3, 15)),
        ("listed_other", date(2026, 3, 15)),
        ("other", date(2025, 6, 15)),
    ):
        turns = un.long_term_on(cls, bought, TODAY)
        assert turns is not None
        assert cg.lot_bucket(cls, bought, turns - timedelta(days=1))[1] == "short"
        assert cg.lot_bucket(cls, bought, turns)[1] == "long"


def test_long_term_on_month_end_clamp():
    # 31 Aug 2026 + 6 months style: Feb is clamped to its last day, the lot turns the day after
    assert un.long_term_on("equity", date(2026, 2, 28), date(2026, 3, 1)) == date(2027, 3, 1)
    assert un.long_term_on("other", date(2026, 2, 28), TODAY) == date(2028, 2, 29)
    assert un.long_term_on("other", date(2024, 2, 29), date(2025, 1, 1)) == date(2026, 3, 1)
    assert un.long_term_on("equity", date(2026, 8, 31), TODAY) == date(2027, 9, 1)
    assert un.long_term_on("equity", date(2025, 2, 28), date(2026, 2, 1)) == date(2026, 3, 1)
    # a leap-day buy date clamps to 28 Feb the next year
    assert un.long_term_on("equity", date(2024, 2, 29), date(2024, 12, 1)) == date(2025, 3, 1)


def test_long_term_on_is_null_when_it_never_comes_or_has_come():
    assert un.long_term_on("equity", date(2025, 1, 1), TODAY) is None  # already long
    assert un.long_term_on("equity", date(2025, 11, 8), TODAY) == date(2026, 11, 9)
    assert un.long_term_on("equity", date(2025, 11, 7), TODAY) is None  # long since today
    assert un.long_term_on("crypto", date(2026, 1, 1), TODAY) is None
    assert un.long_term_on("equity", None, TODAY) is None
    assert un.long_term_on("debt_fund", date(2023, 4, 1), TODAY) is None  # always short
    assert un.long_term_on("debt_fund", date(2025, 1, 1), TODAY) is None  # debt bought before 2023 only


def test_debt_fund_before_april_2023_turns_at_24_months_after_cutoff():
    assert un.long_term_on("debt_fund", date(2023, 3, 31), date(2025, 1, 1)) == date(2025, 4, 1)


def test_debt_fund_after_april_2023_has_no_long_term_date_in_the_holding():
    built = un.build_holding(CASES["debt_fund_after"], TODAY)
    [lot] = built["lots"]
    assert (lot["term"], lot["bucket"], lot["long_term_on"], lot["days_to_long_term"], lot["bucket_after"]) == (
        "short", "slab", None, None, None,
    )  # fmt: skip


def test_days_to_long_term_and_bucket_after():
    h = holding(bought_on=date(2026, 6, 1))
    [lot] = un.build_holding(h, TODAY)["lots"]
    assert lot["long_term_on"] == date(2027, 6, 2)
    assert lot["days_to_long_term"] == (date(2027, 6, 2) - TODAY).days
    assert (lot["bucket"], lot["bucket_after"]) == ("equity_st", "equity_lt")


# --- exemption and harvest -----------------------------------------------------------------


def realised(lt=D(0), lt_old=D(0), lt_set_off=D(0), lt_old_set_off=D(0)):
    return [
        {"key": "equity_lt", "net": lt, "set_off": lt_set_off},
        {"key": "equity_lt_old", "net": lt_old, "set_off": lt_old_set_off},
        {"key": "slab", "net": D(99999), "set_off": D(0)},
    ]


def test_exemption_used_sums_both_equity_long_term_buckets_after_set_off():
    assert un.exemption_used(realised(D(30000), D(20000), D(5000), D(0))) == 45000
    assert un.exemption_used(realised(D(-8000), D(20000))) == 20000  # a net loss counts as 0
    assert un.exemption_used([]) == 0


@pytest.mark.parametrize(
    "lt,lt_old,expected_used,expected_room",
    [
        (D(0), D(0), 0, 125000),
        (D(30000), D(20000), 50000, 75000),
        (D(125000), D(0), 125000, 0),
        (D(200000), D(50000), 250000, 0),  # more than the limit: the room never goes negative
        (D(-5000), D(-1), 0, 125000),
    ],
)
def test_exemption_room_is_limit_minus_used_never_negative(lt, lt_old, expected_used, expected_room):
    report = un.build_report([], 2026, TODAY, realised(lt, lt_old))
    h = report["harvest"]
    assert h["exemption_limit"] == 125000
    assert (h["exemption_used"], h["exemption_room"]) == (expected_used, expected_room)
    assert h["exemption_room"] >= 0


def test_exemption_limit_for_an_old_year():
    report = un.build_report([], 2023, TODAY, realised(D(30000)))
    assert report["harvest"]["exemption_limit"] == 100000 and report["harvest"]["exemption_room"] == 70000


def test_harvest_lists_and_summary():
    holdings = [
        un.build_holding(h, TODAY)
        for h in (
            holding(holding_id=1, name="Gain Eq", value=D(1500)),  # long equity, +500
            holding(holding_id=2, name="Loss Eq", value=D(700), bought_on=date(2026, 3, 1)),  # short -300
            holding(holding_id=3, name="Big Loss Gold", asset_type="gold", stock_kind=None, value=D(400), bought_on=date(2025, 9, 1)),  # -600
            holding(holding_id=4, name="Crypto Loss", asset_type="other", stock_kind=None, other_category="Crypto", value=D(100), bought_on=None),  # -900
            holding(holding_id=5, name="Dateless Loss", asset_type="other", stock_kind=None, other_category="Art", value=D(100), bought_on=None),  # no bucket
            holding(holding_id=6, name="Soon Long", bought_on=date(2025, 12, 1), value=D(1300)),  # turns 2026-12-02
            holding(holding_id=7, name="Later Long", bought_on=date(2026, 3, 15), value=D(1300)),  # turns 2027-03-16, beyond 90 days
        )
    ]
    report = un.build_report(holdings, 2026, TODAY, [])
    harvest = report["harvest"]
    assert [(t["name"], t["gain"]) for t in harvest["loss_lots"]] == [("Big Loss Gold", -600), ("Loss Eq", -300)]
    assert all(t["bucket"] not in (None, "crypto") for t in harvest["loss_lots"])
    [soon] = harvest["turning_long_term"]  # Later Long turns after 90 days, the rest never or later
    assert (soon["name"], soon["long_term_on"], soon["days_to_long_term"]) == ("Soon Long", date(2026, 12, 2), 24)
    assert soon["bucket"] == "equity_st" and soon["bucket_after"] == "equity_lt"
    assert harvest["unrealised_equity_lt_gain"] == 500
    assert report["summary"]["uncounted_lots"] == 1  # the dateless Art lot
    assert report["summary"]["total_gain"] == sum(lot["gain"] for h in holdings for lot in h["lots"])
    keys = [b["key"] for b in report["buckets"]]
    assert keys == [k for k in cg.BUCKET_ORDER if k in keys]
    for b in report["buckets"]:
        assert b["net"] == b["gains"] - b["losses"]
