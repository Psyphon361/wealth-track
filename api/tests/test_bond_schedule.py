"""Bond payment schedule (services/bond_schedule.py) and GET /api/analytics/bond-schedule.
`today` is 2026-11-04 in the pure tests; coupon figures are hand-worked from the module rules."""

from datetime import date
from decimal import Decimal

import pytest

from app.services import bond_schedule as bs
from app.services import valuation
from tests.test_analytics_api import TODAY as API_TODAY  # noqa: F401
from tests.test_analytics_api import fixed_today, seeded, tables  # noqa: F401  (fixtures)
from tests.test_analytics_tax import FY25, FY26, bmaster, bond, tax_today  # noqa: F401
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 4)
ONE = Decimal("395.83")  # 5 x 10,000 at 9.5% over 12, paid in whole paise
ONE_TDS = Decimal("39.58")


def coupon_dates(schedule):
    return [p["date"] for p in schedule if p["kind"] == "coupon"]


def test_fy_of():
    assert bs.fy_of(date(2026, 3, 31)) == "2025-26"
    assert bs.fy_of(date(2026, 4, 1)) == "2026-27"
    assert bs.fy_of(date(2099, 12, 1)) == "2099-00"


def test_monthly_schedule_from_the_purchase_date_to_maturity():
    schedule = bs.payments(bond(), bmaster())
    dates = coupon_dates(schedule)
    # Stepped back from 30 Sep 2027; 30 Jan 2025 is the first one after the 1 Jan 2025 purchase.
    assert dates[0] == date(2025, 1, 30) and dates[-1] == date(2027, 9, 30)
    assert len(dates) == 33 and dates == sorted(dates)
    coupon = schedule[0]
    assert coupon["gross"] == ONE and coupon["tds"] == ONE_TDS
    assert coupon["net"] == Decimal("356.25")
    assert coupon["fy"] == "2024-25"
    assert schedule[-1]["kind"] == "redemption" and len(schedule) == 34


def test_quarterly_half_yearly_and_yearly_schedules():
    quarterly = bs.payments(
        bond(quantity=100, face_value=1000, maturity=date(2027, 12, 15), purchase=date(2026, 10, 1)),
        bmaster(rate=8, frequency="quarterly"),
    )
    assert coupon_dates(quarterly) == [
        date(2026, 12, 15), date(2027, 3, 15), date(2027, 6, 15), date(2027, 9, 15),
        date(2027, 12, 15),
    ]  # fmt: skip
    assert {p["gross"] for p in quarterly if p["kind"] == "coupon"} == {Decimal(2000)}
    half = bs.payments(
        bond(quantity=100, face_value=1000, maturity=date(2027, 2, 10)),
        bmaster(rate=5, frequency="half_yearly"),
    )
    assert coupon_dates(half)[:2] == [date(2025, 2, 10), date(2025, 8, 10)]
    assert {p["gross"] for p in half if p["kind"] == "coupon"} == {Decimal(2500)}
    yearly = bs.payments(
        bond(quantity=100, face_value=1000, maturity=date(2027, 3, 31)),
        bmaster(rate=7, frequency="yearly"),
    )
    assert coupon_dates(yearly) == [date(2025, 3, 31), date(2026, 3, 31), date(2027, 3, 31)]


def test_month_end_dates_clamp_when_stepping_back_from_maturity():
    schedule = bs.payments(bond(maturity=date(2026, 5, 31)), bmaster())
    dates = coupon_dates(schedule)
    assert date(2026, 4, 30) in dates and date(2026, 3, 31) in dates
    assert date(2026, 2, 28) in dates and date(2026, 1, 31) in dates
    assert date(2026, 5, 31) in dates


def test_purchase_date_and_maturity_mid_period():
    # A coupon dated exactly on the purchase date is not paid to the buyer.
    schedule = bs.payments(bond(purchase=date(2026, 9, 30)), bmaster())
    assert coupon_dates(schedule)[0] == date(2026, 10, 30)
    # Bought 15 Oct: the first coupon is 30 Oct; the last is on the maturity date itself.
    schedule = bs.payments(bond(purchase=date(2026, 10, 15), maturity=date(2027, 1, 31)), bmaster())
    assert coupon_dates(schedule) == [
        date(2026, 10, 31), date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31)
    ]  # fmt: skip


def test_redemption_is_face_value_times_quantity_on_the_maturity_date():
    schedule = bs.payments(bond(), bmaster())
    last = schedule[-1]
    assert (last["date"], last["kind"], last["gross"], last["tds"], last["net"]) == (
        date(2027, 9, 30), "redemption", Decimal(50000), 0, Decimal(50000)
    )
    assert last["estimated_value"] is False and last["fy"] == "2027-28"
    # Face value falls back to the master's.
    assert bs.payments(bond(face_value=None), bmaster(face=2000))[-1]["gross"] == Decimal(10000)


def test_sgb_redeems_at_issue_price_per_gram_marked_estimated():
    holding = bond(bond_type="sgb", quantity=5, face_value=None, maturity=date(2027, 6, 1),
                   purchase=date(2026, 8, 1))  # fmt: skip
    master = bmaster(rate=2.5, frequency=None, bond_type="sgb", face=None, issue_price=6000)
    schedule = bs.payments(holding, master)
    assert coupon_dates(schedule) == [date(2026, 12, 1), date(2027, 6, 1)]
    assert {p["gross"] for p in schedule if p["kind"] == "coupon"} == {Decimal(375)}
    assert {p["tds"] for p in schedule} == {0}
    assert schedule[-1]["gross"] == Decimal(30000) and schedule[-1]["estimated_value"] is True
    assert bs.payments(holding, bmaster(rate=2.5, frequency=None, bond_type="sgb", face=None)) is None


def test_on_maturity_bond_has_one_coupon_and_the_redemption_on_the_maturity_date():
    holding = bond(quantity=100, face_value=1000, maturity=date(2027, 1, 1))
    master = bmaster(rate=9, frequency="on_maturity", issue_date=date(2024, 4, 1))
    schedule = bs.payments(holding, master)
    t = valuation._year_fraction(date(2024, 4, 1), date(2027, 1, 1))
    assert [p["kind"] for p in schedule] == ["coupon", "redemption"]
    assert {p["date"] for p in schedule} == {date(2027, 1, 1)}
    assert schedule[0]["gross"] == round(Decimal(100000 * 0.09 * t), 2)
    assert schedule[0]["tds"] == round(schedule[0]["gross"] / 10, 2)
    assert schedule[1]["gross"] == Decimal(100000)
    assert bs.payments(holding, bmaster(rate=9, frequency="on_maturity")) is None


def test_tds_is_ten_percent_of_coupons_for_corporate_and_none_otherwise():
    corporate = bs.payments(bond(), bmaster())
    assert all(p["tds"] == 0 for p in corporate if p["kind"] == "redemption")
    assert all(p["tds"] == round(p["gross"] / 10, 2) for p in corporate if p["kind"] == "coupon")
    other = bs.payments(bond(bond_type="other"), bmaster(bond_type="other"))
    assert other[0]["tds"] > 0
    for item_type, master_type in (("government", "government"), ("corporate", "government"),
                                   ("tax_free", "corporate"), ("corporate", "tax_free"),
                                   ("sgb", "corporate")):  # fmt: skip
        schedule = bs.payments(
            bond(bond_type=item_type), bmaster(bond_type=master_type, issue_price=6000)
        )
        assert {p["tds"] for p in schedule} == {0}, (item_type, master_type)
        assert bs.tds_applies(bond(bond_type=item_type), bmaster(bond_type=master_type)) is False
    assert bs.tds_applies(bond(), bmaster()) is True


def test_by_fy_sums_coupons_per_financial_year():
    holding = bond(quantity=100, face_value=1000, maturity=date(2027, 2, 10))
    schedule = bs.payments(holding, bmaster(rate=5, frequency="half_yearly"))
    rows = bs.by_fy(schedule)
    assert [(r["fy"], r["coupons"]) for r in rows] == [
        ("2024-25", 1), ("2025-26", 2), ("2026-27", 2)
    ]  # fmt: skip
    assert [r["gross"] for r in rows] == [Decimal(2500), Decimal(5000), Decimal(5000)]
    assert [r["tds"] for r in rows] == [Decimal(250), Decimal(500), Decimal(500)]
    assert [r["net"] for r in rows] == [Decimal(2250), Decimal(4500), Decimal(4500)]
    # The redemption (50,000... here 100,000) is not part of a year's coupons.
    assert sum(r["gross"] for r in rows) == Decimal(12500)


def test_window_sums_equal_the_old_bond_coupons_results():
    from app.services import analytics_tax as tax

    cases = [
        (bond(), bmaster()),
        (bond(maturity=date(2026, 5, 31)), bmaster()),
        (bond(purchase=date(2026, 10, 15)), bmaster()),
        (bond(quantity=100, face_value=1000, maturity=date(2027, 12, 15)),
         bmaster(rate=8, frequency="quarterly")),
    ]  # fmt: skip
    for holding, master in cases:
        schedule = bs.payments(holding, master)
        for window in (FY26, FY25, (FY26[0], TODAY)):
            assert tax.bond_coupons(holding, master, *window) == bs.sum_in_window(schedule, *window)
    assert tax.bond_coupons(bond(), None, *FY26) is None
    # Exactly the 12 coupons of FY 2026-27 for the monthly bond; TDS is a tenth.
    schedule = bs.payments(bond(), bmaster())
    assert bs.sum_in_window(schedule, *FY26) == 12 * ONE
    assert bs.sum_in_window(schedule, *FY26, "tds") == 12 * ONE_TDS


def test_schedules_that_cannot_be_worked_out_are_none():
    assert bs.payments(bond(), None) is None
    assert bs.payments(bond(), bmaster(rate=None)) is None
    assert bs.payments(bond(), bmaster(frequency="irregular")) is None
    assert bs.payments(bond(), bmaster(frequency=None)) is None
    assert bs.payments(bond(quantity=0), bmaster()) is None
    assert bs.schedule_view(bond(), None, TODAY) is None


def test_schedule_view_rounds_flags_paid_and_picks_the_next_payment():
    view = bs.schedule_view(bond(), bmaster(), TODAY)
    assert view["id"] == 1 and view["name"] == "Bond" and view["estimated"] is True
    assert view["issuer"] == "Acme Capital Ltd" and view["frequency"] == "monthly"
    assert view["coupon_rate"] == Decimal("9.5") and view["face_value"] == Decimal(10000)
    assert view["tds_rate"] == 10
    first = view["payments"][0]
    assert (first["gross"], first["tds"], first["net"]) == (
        Decimal("395.83"), Decimal("39.58"), Decimal("356.25")
    )
    assert first["paid"] is True and "estimated_value" not in first
    # 30 Nov 2026 is the first coupon after 4 Nov; 30 Oct was paid.
    assert view["next_payment"]["date"] == date(2026, 11, 30)
    assert all(p["paid"] == (p["date"] <= TODAY) for p in view["payments"])
    assert view["payments"][-1]["estimated_value"] is False
    assert view["by_fy"][0] == {
        "fy": "2024-25", "coupons": 3, "gross": Decimal("1187.49"), "tds": Decimal("118.74"),
        "net": Decimal("1068.75"),
    }  # 30 Jan, 28 Feb, 30 Mar 2025
    gov = bs.schedule_view(bond(bond_type="government"), bmaster(bond_type="government"), TODAY)
    assert gov["tds_rate"] == 0
    done = bs.schedule_view(bond(maturity=date(2026, 5, 31)), bmaster(), TODAY)
    assert done["next_payment"] is None


# --- Endpoint ----------------------------------------------------------------------------------


def _get(client, headers, **params):
    return client.get("/api/analytics/bond-schedule", headers=headers, params=params)


def _configure_masters(auth_engine):
    from sqlalchemy import text

    with auth_engine.begin() as conn:
        conn.execute(text(
            "UPDATE bond_master SET coupon_rate = 8, interest_frequency = 'yearly', face_value = 1000 "
            "WHERE id = 1"
        ))  # fmt: skip
        conn.execute(text("UPDATE bond_master SET coupon_rate = 2.5, issue_price = 6000 WHERE id = 2"))


def test_requires_bearer(client):
    assert client.get("/api/analytics/bond-schedule").status_code == 401


def test_endpoint_lists_bonds_with_schedules_and_counts_excluded(
    client, seeded, tax_today, auth_engine  # noqa: F811
):
    _configure_masters(auth_engine)
    body = _get(client, seeded[0]).json()
    assert body["as_of"] == "2026-11-02" and body["excluded"] == 1  # Old Bond has no master
    by_name = {b["name"]: b for b in body["bonds"]}
    assert set(by_name) == {"NHAI 2030", "SGB 2027"}
    nhai = by_name["NHAI 2030"]
    assert nhai["estimated"] is True and nhai["tds_rate"] == 0  # tax-free
    assert [(p["date"], p["kind"], p["gross"], p["paid"]) for p in nhai["payments"]] == [
        ("2027-01-15", "coupon", 800, False), ("2027-01-15", "redemption", 10000, False)
    ]  # fmt: skip
    assert nhai["next_payment"]["date"] == "2027-01-15"
    assert nhai["by_fy"] == [{"fy": "2026-27", "coupons": 1, "gross": 800, "tds": 0, "net": 800}]
    sgb = by_name["SGB 2027"]
    assert [p["date"] for p in sgb["payments"]] == ["2026-12-01", "2027-06-01", "2027-06-01"]
    assert sgb["payments"][-1]["gross"] == 30000 and sgb["payments"][-1]["estimated_value"] is True
    assert sgb["frequency"] == "half_yearly" and sgb["tds_rate"] == 0


def test_endpoint_filters_by_id_and_404s_for_unknown_or_foreign(
    client, seeded, tax_today, auth_engine  # noqa: F811
):
    _configure_masters(auth_engine)
    everything = _get(client, seeded[0]).json()["bonds"]
    nhai = next(b for b in everything if b["name"] == "NHAI 2030")
    single = _get(client, seeded[0], id=nhai["id"]).json()
    assert [b["id"] for b in single["bonds"]] == [nhai["id"]] and single["excluded"] == 0
    for missing in (999999, -1):
        response = _get(client, seeded[0], id=missing)
        assert response.status_code == 404
        body = response.json()
        assert body["message"] == "Bond not found"
        assert body["description"] == "This bond doesn't exist or was deleted."
    # Another user's bond id is also a 404.
    assert _get(client, seeded[1], id=nhai["id"]).status_code == 404
    assert _get(client, seeded[0], id="abc").status_code == 422
