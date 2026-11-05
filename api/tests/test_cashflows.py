"""Money coming in (services/cashflows.py) and GET /api/analytics/inflows. `today` is 2026-11-04 in
the pure tests."""

from datetime import date
from decimal import Decimal

import pytest

from app.services import cashflows, valuation
from tests.test_analytics_api import fixed_today, seeded, tables  # noqa: F401  (fixtures)
from tests.test_analytics_tax import bmaster, bond, item, tax_today  # noqa: F401
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 4)


def rd_item(id_=1, *, instalment=1000, rate=6, start="2026-06-01", months=6, **extra):
    return {
        "id": id_, "label": None, "bank": "Some Bank", "monthly_instalment": instalment,
        "rate": rate, "start_date": start, "tenure_years": 0, "tenure_months": months,
        "tenure_days": 0, "compounding": "quarterly", "status": "active", **extra,
    }  # fmt: skip


def groups(fds=(), rds=(), bonds=(), other=()):
    return [
        {"type": "fd", "items": list(fds)},
        {"type": "rd", "items": list(rds)},
        {"type": "bond", "items": list(bonds)},
        {"type": "stock", "items": list(other)},
        {"type": "mf", "items": list(other)},
    ]


def events_of(body, type_=None):
    return [e for m in body["months"] for e in m["items"] if type_ in (None, e["type"])]


def test_cumulative_fd_matures_with_principal_and_all_the_interest():
    deposit = item(1, "Some Bank", 100000, rate=10, start="2026-04-01", years=1,
                   compounding="simple", payout="cumulative")  # fmt: skip
    body = cashflows.inflows(groups(fds=[deposit]), {}, TODAY)
    (event,) = events_of(body)
    assert (event["date"], event["type"], event["kind"]) == (date(2027, 4, 1), "fd", "maturity")
    assert event["principal"] == Decimal("100000.00") and event["interest"] == Decimal("10000.00")
    month = next(m for m in body["months"] if m["month"] == "2027-04")
    assert (month["interest"], month["principal"]) == (Decimal("10000.00"), Decimal("100000.00"))


def test_payout_fd_pays_interest_on_each_period_and_principal_at_maturity():
    deposit = item(1, "Some Bank", 120000, rate=8, start="2026-02-01", years=1,
                   compounding="quarterly", payout="payout")  # fmt: skip
    body = cashflows.inflows(groups(fds=[deposit]), {}, TODAY, 12)
    events = events_of(body)
    # 2,400 on 1 May, 1 Aug (past) and 1 Nov (past, before 4 Nov), then 1 Feb 2027 and maturity.
    assert [(e["date"], e["kind"], e["interest"], e["principal"]) for e in events] == [
        (date(2027, 2, 1), "interest_payout", Decimal("2400.00"), 0),
        (date(2027, 2, 1), "maturity", 0, Decimal("120000.00")),
    ]  # fmt: skip
    assert body["totals"] == {"interest": Decimal("2400.00"), "principal": Decimal("120000.00")}


def test_payout_fd_with_a_part_period_at_maturity():
    deposit = item(1, "Some Bank", 120000, rate=12, start="2026-09-15", years=0,
                   tenure_months=0, compounding="monthly", payout="payout", tenure_days=45)  # fmt: skip
    events = events_of(cashflows.inflows(groups(fds=[deposit]), {}, TODAY, 12))
    # Maturity 30 Oct 2026 is past: nothing to come.
    assert events == []
    deposit = item(1, "Some Bank", 120000, rate=12, start="2026-10-20", years=0,
                   compounding="monthly", payout="payout", tenure_days=45)  # fmt: skip
    events = events_of(cashflows.inflows(groups(fds=[deposit]), {}, TODAY, 12))
    assert [e["kind"] for e in events] == ["interest_payout", "interest_payout", "maturity"]
    assert events[0]["date"] == date(2026, 11, 20) and events[0]["interest"] == Decimal("1200.00")
    assert events[1]["date"] == date(2026, 12, 4)  # maturity: part-period interest
    assert events[2]["principal"] == Decimal("120000.00") and events[2]["interest"] == 0


def test_rd_matures_with_instalments_as_principal_and_the_interest():
    deposit = rd_item()  # 1,000 a month from 1 Jun 2026 for 6 months: matures 1 Dec 2026
    body = cashflows.inflows(groups(rds=[deposit]), {}, TODAY)
    (event,) = events_of(body)
    assert (event["date"], event["type"], event["kind"]) == (date(2026, 12, 1), "rd", "maturity")
    assert event["principal"] == Decimal("6000.00")
    out = valuation.value_rd(
        type("R", (), dict(monthly_instalment=Decimal(1000), rate=Decimal(6), compounding="quarterly",
                           start_date=date(2026, 6, 1), tenure_years=0, tenure_months=6, tenure_days=0))(),
        date(2026, 12, 1),
    )
    assert event["interest"] == out["current_value"].quantize(Decimal("0.01")) - Decimal("6000.00")
    assert event["interest"] > 0


def test_bond_coupons_and_redemption_are_interest_and_principal():
    holding = bond(quantity=100, face_value=1000, maturity=date(2027, 3, 31), name="NCD",
                   purchase=date(2026, 6, 1))  # fmt: skip
    master = bmaster(rate=8, frequency="quarterly", face=1000)
    body = cashflows.inflows(groups(bonds=[{**holding, "status": "active"}]), {1: master}, TODAY)
    events = events_of(body, "bond")
    # Quarterly 2,000 on 30 Jun (past), 30 Sep (past), 31 Dec 2026 and 31 Mar 2027 + redemption.
    assert [(e["date"], e["kind"], e["interest"], e["principal"]) for e in events] == [
        (date(2026, 12, 31), "coupon", Decimal("2000.00"), 0),
        (date(2027, 3, 31), "coupon", Decimal("2000.00"), 0),
        (date(2027, 3, 31), "redemption", 0, Decimal("100000.00")),
    ]  # fmt: skip
    assert events[0]["name"] == "NCD" and events[0]["id"] == 1
    assert body["types"] == ["bond"]


def test_bonds_without_a_workable_schedule_and_inactive_holdings_give_nothing():
    holding = {**bond(), "status": "active"}
    assert events_of(cashflows.inflows(groups(bonds=[holding]), {}, TODAY)) == []  # no master
    matured = item(1, "Some Bank", 100000, start="2025-01-01", years=1, status="matured")
    sold = {**holding, "status": "matured"}
    assert events_of(
        cashflows.inflows(groups(fds=[matured], bonds=[sold]), {1: bmaster()}, TODAY)
    ) == []


def test_other_asset_types_give_nothing():
    stock = {"id": 1, "status": "active", "name": "Infosys"}
    body = cashflows.inflows(groups(other=[stock]), {}, TODAY)
    assert events_of(body) == [] and body["types"] == []


def test_months_start_with_the_current_one_and_empty_months_are_included():
    deposit = item(1, "Some Bank", 100000, rate=10, start="2026-04-01", years=1,
                   compounding="simple", payout="cumulative")  # fmt: skip
    body = cashflows.inflows(groups(fds=[deposit]), {}, TODAY, 12)
    assert body["as_of"] == TODAY
    assert [m["month"] for m in body["months"]] == [
        "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05", "2027-06",
        "2027-07", "2027-08", "2027-09", "2027-10",
    ]  # fmt: skip
    assert [len(m["items"]) for m in body["months"]] == [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0]
    assert len(cashflows.inflows(groups(), {}, TODAY, 24)["months"]) == 24
    # A maturity 18 months out shows in a 24-month view only.
    far = item(2, "Some Bank", 100000, start="2026-05-01", years=2, compounding="simple",
               payout="cumulative")  # fmt: skip
    assert events_of(cashflows.inflows(groups(fds=[far]), {}, TODAY, 12)) == []
    (event,) = events_of(cashflows.inflows(groups(fds=[far]), {}, TODAY, 24))
    assert event["date"] == date(2028, 5, 1)
    empty = cashflows.inflows(groups(), {}, TODAY)
    assert empty["totals"] == {"interest": 0, "principal": 0} and empty["types"] == []


def test_events_before_today_are_dropped_but_today_counts():
    holding = {**bond(maturity=date(2027, 9, 4), purchase=date(2026, 1, 1)), "status": "active"}
    master = bmaster(rate=12, frequency="monthly")
    body = cashflows.inflows(groups(bonds=[holding]), {1: master}, TODAY, 12)
    first = body["months"][0]["items"]
    assert [e["date"] for e in first] == [date(2026, 11, 4)]  # 4 Nov is today; 4 Oct is past
    assert body["months"][0]["interest"] == Decimal("500.00")


def test_items_are_sorted_by_date_and_totals_and_types_add_up():
    fd1 = item(1, "Some Bank", 100000, rate=10, start="2026-04-01", years=1, compounding="simple",
               payout="cumulative")  # fmt: skip
    holding = {**bond(maturity=date(2027, 4, 1), name="NCD"), "status": "active"}
    body = cashflows.inflows(
        groups(fds=[fd1], rds=[rd_item()], bonds=[holding]), {1: bmaster()}, TODAY, 12
    )
    month = next(m for m in body["months"] if m["month"] == "2027-04")
    assert [e["date"] for e in month["items"]] == sorted(e["date"] for e in month["items"])
    assert month["interest"] == sum(e["interest"] for e in month["items"])
    assert body["totals"]["interest"] == sum(m["interest"] for m in body["months"])
    assert body["totals"]["principal"] == sum(m["principal"] for m in body["months"])
    assert body["types"] == ["fd", "rd", "bond"]


# --- Endpoint ----------------------------------------------------------------------------------


def _get(client, headers, **params):
    return client.get("/api/analytics/inflows", headers=headers, params=params)


def test_requires_bearer(client):
    assert client.get("/api/analytics/inflows").status_code == 401


def test_months_param_accepts_12_and_24_only(client, seeded, tax_today):  # noqa: F811
    assert len(_get(client, seeded[0]).json()["months"]) == 12
    assert len(_get(client, seeded[0], months=24).json()["months"]) == 24
    for bad in (6, 0, 13):
        response = _get(client, seeded[0], months=bad)
        assert response.status_code == 422
        body = response.json()
        assert body["message"] == "Invalid period"
        assert body["description"] == "Choose 12 or 24 months."
    assert _get(client, seeded[0], months="abc").status_code == 422


def test_endpoint_shape_bond_events_and_scoping(client, seeded, tax_today, auth_engine):  # noqa: F811
    from sqlalchemy import text

    with auth_engine.begin() as conn:
        conn.execute(text(
            "UPDATE bond_master SET coupon_rate = 8, interest_frequency = 'yearly', face_value = 1000 "
            "WHERE id = 1"
        ))  # fmt: skip
        conn.execute(text("UPDATE bond_master SET coupon_rate = 2.5, issue_price = 6000 WHERE id = 2"))
    body = _get(client, seeded[0]).json()
    assert body["as_of"] == "2026-11-02"
    assert body["months"][0]["month"] == "2026-11" and len(body["months"]) == 12
    assert set(body["types"]) <= {"fd", "rd", "bond"} and "bond" in body["types"]
    bonds = [(e["date"], e["name"], e["kind"], e["interest"], e["principal"])
             for m in body["months"] for e in m["items"] if e["type"] == "bond"]  # fmt: skip
    assert bonds == [
        ("2026-12-01", "SGB 2027", "coupon", 375, 0),
        ("2027-01-15", "NHAI 2030", "coupon", 800, 0),
        ("2027-01-15", "NHAI 2030", "redemption", 0, 10000),
        ("2027-06-01", "SGB 2027", "coupon", 375, 0),
        ("2027-06-01", "SGB 2027", "redemption", 0, 30000),
    ]
    assert body["totals"]["interest"] == pytest.approx(sum(m["interest"] for m in body["months"]))
    assert body["totals"]["principal"] == pytest.approx(sum(m["principal"] for m in body["months"]))
    # The soft-deleted holdings never appear.
    assert all(e["name"] != "Deleted" for m in body["months"] for e in m["items"])
    # User B owns no bonds.
    other = _get(client, seeded[1]).json()
    assert "bond" not in other["types"]
