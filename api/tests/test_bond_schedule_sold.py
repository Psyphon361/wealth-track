"""A bond fully sold via Sell stops its estimated schedule at the sale date: coupons dated on or
before it, no redemption. Bond-schedule, Interest & TDS and inflows must agree."""

from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.services import bond_schedule as bs
from tests.test_analytics_api import fixed_today, seeded, tables  # noqa: F401  (fixtures)
from tests.test_analytics_tax import bmaster, bond, tax_today  # noqa: F401
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 4)
COUPON = Decimal("395.83")


def kinds(schedule):
    return [p["kind"] for p in schedule]


def test_sale_date_cuts_the_coupons_and_drops_the_redemption():
    sold = {**bond(), "closed_on": date(2026, 10, 15), "exit": {"kind": "sale"}}
    schedule = bs.payments(sold, bmaster())
    assert set(kinds(schedule)) == {"coupon"}
    assert schedule[-1]["date"] == date(2026, 9, 30)  # the 30 Oct coupon was never earned
    assert schedule[0]["date"] == date(2025, 1, 30)
    assert all(p["gross"] == COUPON for p in schedule)


def test_a_coupon_on_the_sale_date_is_included():
    sold = {**bond(), "closed_on": date(2026, 9, 30)}
    assert bs.payments(sold, bmaster())[-1]["date"] == date(2026, 9, 30)
    day_before = {**bond(), "closed_on": date(2026, 9, 29)}
    assert bs.payments(day_before, bmaster())[-1]["date"] == date(2026, 8, 30)


def test_total_and_per_fy_rows_follow_the_cut():
    sold = {**bond(), "closed_on": date(2026, 10, 15)}
    view = bs.schedule_view(sold, bmaster(), TODAY)
    assert "redemption" not in [p["kind"] for p in view["payments"]]
    assert view["next_payment"] is None  # nothing left to come
    last = view["by_fy"][-1]
    assert last["fy"] == "2026-27" and last["coupons"] == 6
    assert last["gross"] == 6 * COUPON
    assert sum(r["coupons"] for r in view["by_fy"]) == len(view["payments"])


def test_sold_before_the_first_coupon_leaves_an_empty_schedule():
    sold = {**bond(), "closed_on": date(2025, 1, 10)}
    assert bs.payments(sold, bmaster()) == []


def test_settled_at_maturity_and_open_bonds_keep_their_redemption():
    settled = {**bond(), "closed_on": date(2027, 9, 30), "exit": {"kind": "maturity"}}
    assert kinds(bs.payments(settled, bmaster()))[-1] == "redemption"
    flagged = {**bond(), "closed_on": date(2027, 9, 30), "settled": True}
    assert kinds(bs.payments(flagged, bmaster()))[-1] == "redemption"
    open_ = bond()
    assert kinds(bs.payments(open_, bmaster()))[-1] == "redemption"
    assert len(bs.payments(settled, bmaster())) == len(bs.payments(open_, bmaster()))


def test_a_partial_sale_leaves_the_schedule_to_the_reduced_quantity():
    partial = bond(quantity=3)  # closed_on stays unset after a partial sale
    schedule = bs.payments(partial, bmaster())
    assert kinds(schedule)[-1] == "redemption" and schedule[-1]["gross"] == Decimal(30000)
    assert schedule[0]["gross"] == Decimal("237.50")


def test_the_planned_sale_entry_is_dropped_after_a_real_sale():
    holding = {**bond(purchase=date(2026, 4, 1), maturity=date(2027, 1, 7)),
               "closed_on": date(2026, 8, 20)}  # fmt: skip
    schedule = bs.payments(holding, bmaster(maturity=date(2027, 12, 7)))
    assert kinds(schedule) == ["coupon"] * 5  # 7 Apr to 7 Aug


# --- Endpoints agree ---------------------------------------------------------------------------


def test_schedule_tax_and_inflows_agree_for_a_sold_bond(
    client, seeded, tax_today, auth_engine  # noqa: F811
):
    headers = seeded[0]
    with auth_engine.begin() as conn:
        conn.execute(text(
            "UPDATE bond_master SET coupon_rate = 8, interest_frequency = 'monthly', "
            "face_value = 1000, bond_type = 'corporate', issuer = 'Acme Capital', "
            "maturity_date = '2027-01-15' WHERE id = 1"
        ))  # fmt: skip
        conn.execute(text(
            "UPDATE bonds SET bond_type = 'corporate', purchase_date = '2026-04-01', "
            "closed_on = '2026-08-20' WHERE name = 'NHAI 2030'"
        ))  # fmt: skip
    # 10 x 1,000 at 8% over 12 = 66.67 a month; 15 Apr to 15 Aug are earned (5 coupons).
    expected = Decimal("333.35")

    schedule = client.get("/api/analytics/bond-schedule", headers=headers).json()
    (view,) = [b for b in schedule["bonds"] if b["name"] == "NHAI 2030"]
    assert [p["kind"] for p in view["payments"]] == ["coupon"] * 5
    assert view["payments"][-1]["date"] == "2026-08-15"
    assert view["next_payment"] is None
    assert view["by_fy"] == [
        {"fy": "2026-27", "coupons": 5, "gross": float(expected), "tds": 33.35,
         "net": 300.0}
    ]  # fmt: skip

    tax = client.get("/api/analytics/tax", headers=headers, params={"fy": 2026}).json()
    holdings = [h for p in tax["payers"] for h in p["holdings"] if h["name"] == "NHAI 2030"]
    assert len(holdings) == 1
    assert holdings[0]["interest_projected"] == float(expected)
    assert [p["date"] for p in holdings[0]["payments"]] == [p["date"] for p in view["payments"]]
    assert holdings[0]["tds_estimate"] == 33.35

    inflows = client.get("/api/analytics/inflows", headers=headers, params={"months": 24}).json()
    mine = [e for m in inflows["months"] for e in m["items"] if e["name"] == "NHAI 2030"]
    assert mine == []  # nothing comes in after the sale: no coupons, no redemption
