"""Closing holdings, pure maths: sale amounts and cost, FIFO, validation, status, net worth."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.routers.portfolio import build_dashboard, build_groups
from app.services import exits, networth
from app.services.exits import ExitError
from tests.conftest import make_bond, make_fd, make_gold, make_other, make_stock

D = Decimal
TODAY = date(2026, 11, 7)


def txn(day, kind, units, amount):
    return SimpleNamespace(txn_date=day, kind=kind, units=D(units), amount=D(amount))


def sale(slug="stock", **overrides):
    args = dict(
        held=D("100"), sale_date=date(2026, 11, 1), start=date(2026, 1, 1), today=TODAY,
        quantity=D("40"), price=D("80"), amount=None, charges=D("0"),
    )  # fmt: skip
    args.update(overrides)
    return exits.check_sale(slug, **args)


# --- amounts -------------------------------------------------------------------------------


def test_hand_checked_partial_stock_sale():
    # 100 shares at an average of 50, sell 40 at 80 with 20 of charges.
    plan = sale(charges=D("20"))
    assert plan.gross == D("3200.00")
    assert plan.amount == D("3180.00")
    assert plan.full is False
    cost = exits.sale_cost("stock", held=D("100"), invested=D("5000"), quantity=D("40"), full=False)
    assert cost == D("2000.00")
    left, left_invested, avg_nav = exits.remaining_after("stock", D("100"), D("5000"), D("40"), cost)
    assert left == D("60") and left_invested == D("3000.00") and avg_nav is None


def test_amount_rounds_half_up_to_paise():
    assert exits.gross_amount(D("3"), D("0.125")) == D("0.38")  # 0.375
    plan = sale(quantity=D("3"), price=D("100.005"), charges=D("0.50"))
    assert plan.amount == D("299.52")  # 300.015 -> 300.02 - 0.50


def test_units_round_to_three_places():
    assert exits.units(D("1.2345")) == D("1.235")


def test_selling_everything_is_full_and_costs_the_invested_amount():
    plan = sale(quantity=D("100"))
    assert plan.full is True
    assert exits.sale_cost(
        "stock", held=D("100"), invested=D("5000"), quantity=D("100"), full=True
    ) == D("5000.00")


def test_proportional_cost_rounds_half_up():
    assert exits.proportional_cost(D("10000"), D("30"), D("10")) == D("3333.33")
    assert exits.proportional_cost(D("10000"), D("30"), D("20")) == D("6666.67")
    assert exits.proportional_cost(D("1000"), D("0"), D("1")) == D("0")


# --- FIFO ----------------------------------------------------------------------------------


def two_lots():
    return [
        txn(date(2026, 1, 1), "purchase", "10", "1000"),
        txn(date(2026, 2, 1), "purchase", "10", "2000"),
    ]


def test_fifo_sells_the_oldest_units_first():
    # 10 units at 100 each, then 10 units at 200 each: 15 units cost 1,000 + 5 x 200.
    assert exits.fifo_cost(two_lots(), D("15")) == D("2000.00")
    assert exits.fifo_cost(two_lots(), D("5")) == D("500.00")
    assert exits.fifo_cost(two_lots(), D("20")) == D("3000.00")


def test_fifo_skips_units_already_redeemed():
    txns = [*two_lots(), txn(date(2026, 3, 1), "redemption", "5", "700")]
    # 5 units of the first lot are gone (cost 500); 5 left at 100 then 10 at 200.
    assert exits.fifo_cost(txns, D("10")) == D("1500.00")  # 500 + 5 x 200
    assert exits.fifo_cost(txns, D("15")) == D("2500.00")


def test_fifo_orders_by_date_not_list_order():
    assert exits.fifo_cost(list(reversed(two_lots())), D("10")) == D("1000.00")


def test_fifo_rejects_more_units_than_remain():
    with pytest.raises(ValueError):
        exits.fifo_cost(two_lots(), D("20.5"))


def test_fund_sale_cost_uses_fifo_when_transactions_match_the_holding():
    cost = exits.sale_cost(
        "mf", held=D("20"), invested=D("3000"), quantity=D("15"), full=False, txns=two_lots()
    )
    assert cost == D("2000.00")


def test_fund_sale_cost_is_pro_rata_when_transactions_do_not_match():
    cost = exits.sale_cost(
        "mf", held=D("25"), invested=D("3000"), quantity=D("5"), full=False, txns=two_lots()
    )
    assert cost == D("600.00")


def test_cost_never_exceeds_the_invested_amount():
    cost = exits.sale_cost(
        "mf", held=D("20"), invested=D("2500"), quantity=D("20"), full=False, txns=two_lots()
    )
    assert cost == D("2500.00")
    # FIFO branch (invested within 1.00 of the lots' 3,000): still capped at invested.
    cost = exits.sale_cost(
        "mf", held=D("20"), invested=D("2999.50"), quantity=D("20"), full=False, txns=two_lots()
    )
    assert cost == D("2999.50")


def fund_cost(invested, quantity="15", held="20", txns=None):
    return exits.sale_cost(
        "mf",
        held=D(held),
        invested=D(invested),
        quantity=D(quantity),
        full=False,
        txns=two_lots() if txns is None else txns,
    )


def test_unedited_fund_uses_fifo():
    assert fund_cost("3000") == D("2000.00")  # not 3000 x 15/20 = 2250


def test_edited_fund_is_pro_rata_of_the_edited_amount():
    assert fund_cost("4000") == D("3000.00")  # 4000 x 15/20
    assert fund_cost("2000") == D("1500.00")


def test_invested_within_a_rupee_of_the_lots_is_still_fifo():
    assert fund_cost("3000.50") == D("2000.00")
    assert fund_cost("2999.50") == D("2000.00")


def test_invested_exactly_one_rupee_off_is_fifo_and_a_paisa_more_is_pro_rata():
    assert fund_cost("3001.00") == D("2000.00")
    assert fund_cost("2999.00") == D("2000.00")
    assert fund_cost("3001.01") == D("2250.76")  # 3001.01 x 15/20 = 2250.7575
    assert fund_cost("2998.99") == D("2249.24")  # 2998.99 x 15/20 = 2249.2425


def test_fund_with_an_earlier_redemption_is_fifo_when_invested_is_the_remaining_cost():
    txns = [*two_lots(), txn(date(2026, 3, 1), "redemption", "5", "700")]
    # 15 units left: 5 at 100, 10 at 200 = 2,500. Sell 10: 500 + 5 x 200 = 1,500.
    assert fund_cost("2500", quantity="10", held="15", txns=txns) == D("1500.00")
    # Invested edited to 3,000 (the purchase sum): pro rata, 3000 x 10/15.
    assert fund_cost("3000", quantity="10", held="15", txns=txns) == D("2000.00")


def test_fund_whose_transactions_do_not_match_the_units_is_pro_rata():
    assert fund_cost("3000", quantity="5", held="25") == D("600.00")
    assert fund_cost("3000", quantity="5", held="19.5") == D("769.23")


def test_fund_without_transactions_is_pro_rata():
    assert fund_cost("3000", txns=[]) == D("2250.00")


def test_full_sale_of_an_edited_fund_costs_the_invested_amount():
    cost = exits.sale_cost(
        "mf", held=D("20"), invested=D("4000"), quantity=D("20"), full=True, txns=two_lots()
    )
    assert cost == D("4000.00")


def test_invested_matches_lots_helper():
    assert exits.invested_matches_lots(two_lots(), D("20"), D("3000")) is True
    assert exits.invested_matches_lots(two_lots(), D("20"), D("3001.01")) is False
    with pytest.raises(ValueError):
        exits.invested_matches_lots(two_lots(), D("25"), D("3000"))


def test_fund_remaining_after_a_partial_sale_recomputes_average_nav():
    left, invested, avg_nav = exits.remaining_after("mf", D("20"), D("3000"), D("15"), D("2000"))
    assert left == D("5") and invested == D("1000.00")
    assert avg_nav == D("200.0000")
    _, _, avg = exits.remaining_after("mf", D("30"), D("1000"), D("10"), D("333.33"))
    assert avg == D("33.3335")  # 666.67 / 20
    _, _, avg = exits.remaining_after("mf", D("40"), D("1"), D("8"), D("0"))
    assert avg == D("0.0313")  # 1 / 32 = 0.03125 rounds half up


# --- partial sales that would leave nothing -------------------------------------------------


def test_remainder_floor_is_a_paisa_or_half_a_hundredth_of_a_paisa_a_unit_for_funds():
    assert exits.remainder_floor("stock", D("5")) == D("0.01")
    assert exits.remainder_floor("mf", D("20")) == D("0.01")
    assert exits.remainder_floor("mf", D("400")) == D("0.02")
    assert exits.remainder_floor("mf", D("400.001")) == D("0.03")  # 0.02000005 rounds up


def test_fifo_partial_sale_that_takes_all_the_cost_is_refused():
    # Lots cost 1,000.00 + 0.01; invested 1,000.00 is within 1.00 of that, so FIFO applies.
    lots = [
        txn(date(2026, 1, 1), "purchase", "10", "1000"),
        txn(date(2026, 2, 1), "purchase", "10", "0.01"),
    ]
    cost = exits.sale_cost(
        "mf", held=D("20"), invested=D("1000"), quantity=D("10"), full=False, txns=lots
    )
    assert cost == D("1000.00")  # the whole invested amount, 10 units still held
    with pytest.raises(exits.ExitRefused) as caught:
        exits.check_remainder("mf", D("20"), D("1000"), D("10"), cost)
    assert caught.value.loc == ("quantity",)
    assert caught.value.message == "Can't sell part of this holding"
    assert caught.value.description == (
        "The recorded cost doesn't cover what would be left. Fix the invested amount, or sell all of it."
    )


def test_proportional_partial_sale_that_rounds_the_remainder_to_zero_is_refused():
    for slug in ("mf", "gold", "bond"):
        cost = exits.sale_cost(slug, held=D("3"), invested=D("0.01"), quantity=D("2"), full=False)
        assert cost == D("0.01")
        with pytest.raises(exits.ExitRefused):
            exits.check_remainder(slug, D("3"), D("0.01"), D("2"), cost)


def test_remainder_exactly_at_the_floor_passes_and_one_paisa_below_is_refused():
    exits.check_remainder("gold", D("3"), D("0.02"), D("2"), D("0.01"))  # left 0.01
    exits.check_remainder("mf", D("500"), D("0.12"), D("100"), D("0.10"))  # 400 units: floor 0.02
    with pytest.raises(exits.ExitRefused):
        exits.check_remainder("mf", D("500"), D("0.11"), D("100"), D("0.10"))  # left 0.01 < 0.02


def test_a_cost_already_below_the_floor_is_refused_even_with_nothing_taken():
    with pytest.raises(exits.ExitRefused):
        exits.check_remainder("stock", D("10"), D("0"), D("4"), D("0"))


def test_a_normal_partial_sale_passes_and_a_full_sale_is_never_checked():
    exits.check_remainder("mf", D("20"), D("3000"), D("15"), D("2000"))
    plan = sale("mf", held=D("3"), quantity=D("3"), price=D("1"))
    assert plan.full  # record_sale skips check_remainder for it: cost is the invested amount


# --- validation ----------------------------------------------------------------------------


def error_of(**kw):
    slug = kw.pop("slug", "stock")
    with pytest.raises(ExitError) as caught:
        sale(slug, **kw)
    return caught.value.loc, caught.value.message


def test_date_cannot_be_in_the_future_or_before_the_purchase():
    assert error_of(sale_date=date(2026, 11, 8)) == (("date",), "Date can't be in the future")
    assert error_of(sale_date=date(2025, 12, 31)) == (
        ("date",), "Date can't be before the purchase date"
    )
    assert sale(sale_date=TODAY, start=TODAY).full is False  # same day is fine


def test_other_without_a_start_date_has_no_lower_bound():
    assert sale("other", held=None, quantity=None, price=None, amount=D("500"), start=None).full


def test_quantity_rules():
    assert error_of(quantity=None) == (("quantity",), "Required")
    assert error_of(quantity=D("100.5")) == (("quantity",), "Must be a whole number")
    assert error_of(quantity=D("101")) == (("quantity",), "Can't sell more than you hold")
    assert error_of(slug="bond", quantity=D("1.5")) == (("quantity",), "Must be a whole number")
    # A fund or gold can be sold in fractions.
    assert sale("mf", held=D("10.5"), quantity=D("10.25")).full is False
    assert sale("gold", held=D("10.5"), quantity=D("10.5")).full is True


def test_price_and_charges_rules():
    assert error_of(price=None) == (("price",), "Required")
    assert error_of(price=D("0.001"), quantity=D("1")) == (("price",), "Must be greater than 0")
    assert error_of(charges=D("3200")) == (("charges",), "Charges must be less than the sale value")
    assert sale(charges=D("3199.99")).amount == D("0.01")


def test_other_needs_an_amount_and_is_always_sold_whole():
    kw = dict(held=None, quantity=None, price=None, start=None)
    with pytest.raises(ExitError) as caught:
        sale("other", amount=None, **kw)
    assert (caught.value.loc, caught.value.message) == (("amount",), "Required")
    plan = sale("other", amount=D("12000"), charges=D("100"), **kw)
    assert plan.full and plan.quantity is None and plan.amount == D("11900.00")


# --- status and listing --------------------------------------------------------------------


def test_holding_status():
    assert exits.holding_status("stock", make_stock(), TODAY) == "active"
    assert exits.holding_status("stock", make_stock(closed_on=date(2026, 5, 1)), TODAY) == "sold"
    live = make_bond(maturity_date=date(2027, 1, 1))
    assert exits.holding_status("bond", live, TODAY) == "active"
    assert exits.holding_status("bond", make_bond(maturity_date=TODAY), TODAY) == "matured"
    sold_early = make_bond(maturity_date=date(2027, 1, 1), closed_on=date(2026, 6, 1))
    assert exits.holding_status("bond", sold_early, TODAY) == "sold"


def test_sold_holdings_are_excluded_from_totals_and_counted_as_closed():
    sold = make_stock(master_id=None, closed_on=date(2026, 6, 1))
    kept = make_stock()
    group = next(g for g in build_groups({"stock": [sold, kept]}, TODAY) if g["type"] == "stock")
    assert [i["status"] for i in group["items"]] == ["sold", "active"]
    assert group["count"] == 1
    assert group["closed_count"] == 1 and group["matured_count"] == 1
    assert group["totals"]["invested"] == D("1000.00")
    assert group["items"][0]["closed_on"] == "2026-06-01"
    assert group["items"][1]["closed_on"] is None
    dash = build_dashboard(build_groups({"stock": [sold, kept]}, TODAY))
    assert dash["total_invested"] == D("1000.00")
    row = next(r for r in dash["by_type"] if r["type"] == "stock")
    assert row["closed_count"] == 1 and row["count"] == 1


def test_items_carry_default_exit_fields():
    group = next(g for g in build_groups({"stock": [make_stock()]}, TODAY) if g["type"] == "stock")
    item = group["items"][0]
    assert item["settled"] is False and item["exit"] is None and item["maturity_amount"] is None


def matured_groups():
    # A bond that matured (face 1,000 x 10) and an FD that matured on 2026-10-01.
    bond = make_bond(maturity_date=date(2026, 10, 20), purchase_date=date(2026, 1, 1))
    fd = make_fd(
        bank="Old Bank", principal=D("1000"), start_date=date(2025, 10, 1), payout_type="payout"
    )
    return bond, fd, build_groups({"bond": [bond], "fd": [fd]}, TODAY)


def test_unsettled_lists_matured_deposits_and_bonds_without_a_maturity_exit():
    bond, fd, groups = matured_groups()
    result = exits.unsettled(groups)
    assert result["count"] == 2
    assert result["amount"] == D("11000.00")  # bond 10 x 1,000 + payout FD principal 1,000
    assert [(i["type"], i["id"], i["amount"]) for i in result["items"]] == [
        ("fd", fd.id, D("1000.00")),
        ("bond", bond.id, D("10000.00")),
    ]


def test_apply_exit_info_marks_settled_and_removes_it_from_unsettled():
    bond, fd, groups = matured_groups()
    exits.apply_exit_info(groups, {})
    items = {g["type"]: g["items"][0] for g in groups if g["items"]}
    assert items["bond"]["maturity_amount"] == 10000.0 and items["fd"]["maturity_amount"] == 1000.0

    summary = {"id": 5, "kind": "maturity", "amount": 10000.0}
    exits.apply_exit_info(groups, {("bond", bond.id): {"exit": summary, "settled": True}})
    assert items["bond"]["settled"] is True and items["bond"]["exit"] == summary
    assert items["bond"]["maturity_amount"] == 10000.0  # set earlier; not recomputed once settled
    assert [i["type"] for i in exits.unsettled(groups)["items"]] == ["fd"]


# --- net worth history ---------------------------------------------------------------------


def history(range_key="1m", **holdings):
    return networth.build_history(
        range_key, TODAY, holdings, {}, {}, holdings.pop("txns", {}), (D("0"), D("0"))
    )


def point(result, day):
    return next(p for p in result["points"] if p["date"] == day)


def test_net_worth_counts_a_sold_holding_until_its_closing_day():
    stock = make_stock(buy_date=date(2026, 9, 1), closed_on=date(2026, 10, 20))
    gold = make_gold(purchase_date=date(2026, 9, 1), closed_on=date(2026, 10, 20))
    other = make_other(
        value_date=date(2026, 9, 1), invested_amount=D("100"), closed_on=date(2026, 10, 20)
    )
    result = history(stock=[stock], gold=[gold], other=[other])
    held = point(result, "2026-10-19")
    assert held["invested"] == D("1000.00") + D("50000.00") + D("100.00")
    assert point(result, "2026-10-20")["invested"] == D("0.00")
    assert point(result, "2026-10-21")["invested"] == D("0.00")


def test_net_worth_stops_a_bond_sold_before_maturity():
    bond = make_bond(
        purchase_date=date(2026, 9, 1), maturity_date=date(2027, 9, 1), closed_on=date(2026, 10, 10)
    )
    result = history(bond=[bond])
    assert point(result, "2026-10-09")["invested"] == D("10000.00")
    assert point(result, "2026-10-10")["invested"] == D("0.00")


def test_net_worth_of_a_fund_sold_out_follows_its_transactions():
    mf = SimpleNamespace(
        id=1, scheme_code=100, units=D("10"), invested_amount=D("1000"),
        purchase_date=date(2026, 9, 1), closed_on=date(2026, 10, 10),
    )  # fmt: skip
    txns = {
        1: [
            txn(date(2026, 9, 1), "purchase", "10", "1000"),
            txn(date(2026, 10, 10), "redemption", "10", "1200"),
        ]
    }
    assert networth.txns_match(mf, txns[1]) is True  # a sold-out fund nets to zero units
    result = networth.build_history(
        "1m", TODAY, {"mf": [mf]}, {}, {}, txns, (D("0"), D("0"))
    )
    assert point(result, "2026-10-09")["invested"] == D("1000.00")
    assert point(result, "2026-10-10")["invested"] == D("0.00")


def test_net_worth_of_a_fund_without_matching_transactions_stops_at_closing():
    mf = SimpleNamespace(
        id=2, scheme_code=100, units=D("10"), invested_amount=D("1000"),
        purchase_date=date(2026, 9, 1), closed_on=date(2026, 10, 10),
    )  # fmt: skip
    result = networth.build_history("1m", TODAY, {"mf": [mf]}, {}, {}, {}, (D("0"), D("0")))
    assert point(result, "2026-10-09")["invested"] == D("1000.00")
    assert point(result, "2026-10-10")["invested"] == D("0.00")
