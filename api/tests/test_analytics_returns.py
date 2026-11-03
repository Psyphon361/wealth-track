"""Returns (XIRR) maths and GET /api/analytics/returns. The pure tests build valued items by hand
(today = 2026-11-02); the endpoint test reuses test_analytics_api's seeded portfolio."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import NpsNavHistory
from app.routers import analytics_returns as returns_router
from app.services import analytics_returns as ar
from app.services.valuation import mf_xirr
from tests.test_analytics_api import TODAY, seeded, tables  # noqa: F401  (fixtures)
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

D = Decimal


def _txn(day, kind, units, amount):
    return SimpleNamespace(txn_date=day, kind=kind, units=D(units), amount=D(amount))


def _fd(id_, invested, current, start=date(2025, 11, 2), status="active"):
    return {
        "id": id_, "bank": f"Bank {id_}", "label": None, "status": status,
        "invested": D(invested), "current_value": D(current), "start_date": start,
    }  # fmt: skip


def _group(slug, *items):
    return {"type": slug, "label": slug.upper(), "items": list(items)}


# --- Flow builders -----------------------------------------------------------------------------


def test_single_flow_types_use_their_own_start_date():
    cases = {
        "fd": ("start_date", {}),
        "bond": ("purchase_date", {}),
        "stock": ("buy_date", {"price": D(10)}),
        "gold": ("purchase_date", {"rate_per_gram": D(6000)}),
    }
    for slug, (field, extra) in cases.items():
        item = {"invested": D(1000), "current_value": D(1100), field: date(2025, 11, 2), **extra}
        built = ar.holding_flows(slug, item, TODAY)
        assert built.reason is None and built.basis == "purchase_date", slug
        assert built.flows == [(date(2025, 11, 2), D(-1000)), (TODAY, D(1100))], slug


def test_rd_flows_one_per_paid_instalment_up_to_today():
    item = {
        "monthly_instalment": D(1000), "start_date": date(2026, 8, 2),
        "maturity_date": date(2027, 2, 2), "current_value": D(4100),
    }  # fmt: skip
    built = ar.holding_flows("rd", item, TODAY)
    assert built.basis == "instalments"
    assert built.flows == [
        (date(2026, 8, 2), D(-1000)),
        (date(2026, 9, 2), D(-1000)),
        (date(2026, 10, 2), D(-1000)),
        (date(2026, 11, 2), D(-1000)),
        (TODAY, D(4100)),
    ]


def test_rd_that_has_not_started_has_no_flows():
    item = {
        "monthly_instalment": D(1000), "start_date": date(2026, 12, 2),
        "maturity_date": date(2027, 6, 2), "current_value": D(0),
    }  # fmt: skip
    assert ar.holding_flows("rd", item, TODAY).reason == "no_flows"


def _mf(**extra):
    return {
        "units": D(200), "invested": D(6000), "current_value": D(8000), "nav": D(40),
        "purchase_date": date(2024, 6, 10), **extra,
    }  # fmt: skip


def test_mf_uses_transactions_when_net_units_match():
    txns = [
        _txn(date(2023, 1, 10), "purchase", 100, 3000),
        _txn(date(2024, 6, 10), "purchase", 100, 3000),
    ]
    built = ar.holding_flows("mf", _mf(), TODAY, txns)
    assert built.basis == "transactions"
    assert built.flows == [
        (date(2023, 1, 10), D(-3000)),
        (date(2024, 6, 10), D(-3000)),
        (TODAY, D(8000)),
    ]


def test_mf_redemption_is_money_back_and_units_net_off():
    txns = [
        _txn(date(2024, 1, 1), "purchase", 300, 9000),
        _txn(date(2025, 1, 1), "redemption", 100, 4000),
    ]
    built = ar.holding_flows("mf", _mf(), TODAY, txns)
    assert built.basis == "transactions"
    assert built.flows[:2] == [(date(2024, 1, 1), D(-9000)), (date(2025, 1, 1), D(4000))]


def test_mf_falls_back_to_purchase_date_when_units_do_not_match():
    txns = [_txn(date(2023, 1, 10), "purchase", 100, 3000)]
    built = ar.holding_flows("mf", _mf(), TODAY, txns)
    assert built.basis == "purchase_date"
    assert built.flows == [(date(2024, 6, 10), D(-6000)), (TODAY, D(8000))]


def test_mf_flows_give_the_same_rate_as_mf_xirr():
    txns = [
        _txn(date(2023, 1, 10), "purchase", 100, 3000),
        _txn(date(2024, 6, 10), "purchase", 100, 3000),
    ]
    item = _mf()
    built = ar.holding_flows("mf", item, TODAY, txns)
    pct, _ = ar.return_of(built.flows, item["invested"], item["current_value"] - item["invested"], TODAY)
    expected, basis, _ = mf_xirr(D(200), D(6000), date(2024, 6, 10), D(8000), txns, TODAY)
    assert (pct, "transactions") == (expected, basis)


def test_other_needs_invested_amount_and_acquired_date():
    base = {"current_value": D(120), "value_date": TODAY}
    assert ar.holding_flows("other", base, TODAY).reason == "other_without_invested"
    only_amount = {**base, "invested_amount": D(100)}
    assert ar.holding_flows("other", only_amount, TODAY).reason == "other_without_invested"
    full = {**only_amount, "acquired_on": date(2025, 11, 2)}
    built = ar.holding_flows("other", full, TODAY)
    assert built.flows == [(date(2025, 11, 2), D(-100)), (TODAY, D(120))]


def test_priced_types_valued_at_cost_are_excluded():
    for slug, field in (("stock", "price"), ("mf", "nav"), ("gold", "rate_per_gram")):
        item = {"invested": D(1000), "current_value": D(1000), field: None}
        assert ar.holding_flows(slug, item, TODAY).reason == "at_cost", slug


def test_cash_pf_and_nps_have_no_flows():
    for slug in ("cash", "pf", "nps"):
        assert ar.holding_flows(slug, {"current_value": D(1)}, TODAY).reason == "no_flows"


# --- Under one year, XIRR and aggregation ------------------------------------------------------


def test_exactly_365_days_is_annualised():
    flows = [(date(2025, 11, 2), D(-100)), (TODAY, D(110))]
    assert ar.return_of(flows, D(100), D(10), TODAY) == (D("10.00"), True)


def test_under_a_year_gives_absolute_return_not_xirr():
    flows = [(date(2025, 11, 3), D(-1000)), (TODAY, D(1100))]  # 364 days
    assert ar.return_of(flows, D(1000), D(100), TODAY) == (D("10.00"), False)


def test_under_a_year_with_nothing_invested_has_no_percent():
    flows = [(date(2026, 6, 1), D(0)), (TODAY, D(0))]
    assert ar.return_of(flows, D(0), D(0), TODAY) == (None, False)


def test_group_flows_are_concatenated_before_xirr():
    groups = [_group("fd", _fd(1, 1000, 1100), _fd(2, 1000, 1200))]
    out = ar.returns(groups, TODAY)
    fd = out["by_type"][0]
    # -2000 a year ago, +2300 today
    assert (fd["invested"], fd["current"], fd["gain"]) == (D("2000.00"), D("2300.00"), D("300.00"))
    assert (fd["return_pct"], fd["annualised"], fd["basis"]) == (D("15.00"), True, "purchase_date")
    assert out["overall"]["return_pct"] == D("15.00")
    assert fd["since"] == date(2025, 11, 2) and fd["holdings"] == 2


def test_group_is_not_annualised_when_its_earliest_flow_is_young():
    young = _fd(2, 1000, 1050, start=date(2026, 8, 2))
    out = ar.returns([_group("fd", _fd(1, 1000, 1100), young)], TODAY)
    # earliest flow is a year old, so annualised; the young one alone is absolute
    assert out["by_type"][0]["annualised"] is True
    only_young = ar.returns([_group("fd", young)], TODAY)
    assert only_young["overall"]["return_pct"] == D("5.00")
    assert only_young["overall"]["annualised"] is False
    assert only_young["best"] == [] and only_young["worst"] == []


def test_classes_split_equity_debt_and_mixed_basis():
    stock = {
        "id": 7, "name": "Acme", "status": "active", "master_id": None, "price": D(12),
        "invested": D(1000), "current_value": D(1200), "buy_date": date(2025, 11, 2),
    }  # fmt: skip
    groups = [_group("fd", _fd(1, 1000, 1100)), _group("stock", stock)]
    out = ar.returns(groups, TODAY)
    assert [c["key"] for c in out["by_class"]] == ["equity", "debt"]
    assert out["by_class"][0]["return_pct"] == D("20.00")
    assert out["by_class"][1]["return_pct"] == D("10.00")
    assert [t["key"] for t in out["by_type"]] == ["fd", "stock"]
    assert out["overall"]["basis"] == "purchase_date"
    mf = {
        "id": 3, "scheme_name": "Fund", "status": "active", "scheme_code": None, "nav": D(2),
        "category": "equity", "units": D(10), "invested": D(500), "current_value": D(600),
        "purchase_date": date(2025, 11, 2),
    }  # fmt: skip
    txns = {3: [_txn(date(2025, 11, 2), "purchase", 10, 500)]}
    mixed = ar.returns(groups + [_group("mf", mf)], TODAY, mf_transactions=txns)
    assert mixed["overall"]["basis"] == "mixed"


def test_matured_holdings_are_left_out():
    groups = [_group("fd", _fd(1, 1000, 1100), _fd(2, 5000, 6000, status="matured"))]
    out = ar.returns(groups, TODAY)
    assert out["overall"]["holdings"] == 1 and out["overall"]["invested"] == D("1000.00")


def test_exclusions_are_counted_by_reason():
    cash = {"id": 1, "name": "Wallet", "status": "active", "current_value": D(10)}
    stock = {
        "id": 2, "name": "Unpriced", "status": "active", "master_id": None, "price": None,
        "invested": D(10), "current_value": D(10), "buy_date": date(2025, 1, 1),
    }  # fmt: skip
    other = {
        "id": 3, "name": "Art", "status": "active", "invested_amount": None,
        "current_value": D(10), "acquired_on": None,
    }  # fmt: skip
    out = ar.returns([_group("cash", cash), _group("stock", stock), _group("other", other)], TODAY)
    assert out["excluded"] == {"at_cost": 1, "no_flows": 1, "other_without_invested": 1}
    assert out["overall"] is None and out["by_class"] == [] and out["by_type"] == []


# --- Best and worst ----------------------------------------------------------------------------


def test_best_and_worst_are_ordered_and_never_overlap():
    currents = [1010, 1070, 1030, 1090, 1050, 1020, 1080]  # ids 1..7, returns 1%..9%
    groups = [_group("fd", *[_fd(i + 1, 1000, c) for i, c in enumerate(currents)])]
    out = ar.returns(groups, TODAY)
    assert [h["id"] for h in out["best"]] == [4, 7, 2, 5, 3]
    assert [h["return_pct"] for h in out["best"]] == [D(9), D(8), D(7), D(5), D(3)]
    assert [h["id"] for h in out["worst"]] == [1, 6]
    assert out["worst"][0] == {
        "type": "fd", "id": 1, "name": "Bank 1", "return_pct": D("1.00"), "gain": D("10.00"),
    }


def test_young_holdings_are_not_ranked():
    groups = [_group("fd", _fd(1, 1000, 1100), _fd(2, 1000, 1500, start=date(2026, 9, 1)))]
    out = ar.returns(groups, TODAY)
    assert [h["id"] for h in out["best"]] == [1]


# --- Reference rates ---------------------------------------------------------------------------


def test_nav_cagr_is_annual_growth_of_the_nav():
    # 20 -> 30 over exactly 730 days: sqrt(1.5) - 1
    assert ar.nav_cagr(D(20), D(30), date(2024, 11, 2), TODAY) == D("22.47")


def test_nav_cagr_needs_both_navs_and_a_year():
    assert ar.nav_cagr(None, D(30), date(2024, 11, 2), TODAY) is None
    assert ar.nav_cagr(D(20), None, date(2024, 11, 2), TODAY) is None
    assert ar.nav_cagr(D(20), D(30), date(2026, 1, 1), TODAY) is None


def test_rates_list_pf_interest_and_nps_cagr():
    pf = {"id": 1, "name": "EPF", "status": "active", "interest_rate": D("8.25")}
    nps = [
        {"id": 5, "scheme_name": "Scheme E", "status": "active", "nav": D(30),
         "start_date": date(2024, 11, 2)},
        {"id": 6, "scheme_name": "Scheme G", "status": "active", "nav": D(30),
         "start_date": date(2024, 11, 2)},
    ]  # fmt: skip
    out = ar.rates([_group("pf", pf), _group("nps", *nps)], {5: D(20)}, TODAY)
    assert [(r["type"], r["id"], r["basis"], r["rate_pct"]) for r in out] == [
        ("pf", 1, "interest_rate", D("8.25")),
        ("nps", 5, "nav_cagr", D("22.47")),
        ("nps", 6, "nav_cagr", None),
    ]


# --- Endpoint ----------------------------------------------------------------------------------


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(returns_router, "date", _FixedDate)


def _get(client, headers) -> dict:
    response = client.get("/api/analytics/returns", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_bearer(client):
    assert client.get("/api/analytics/returns").status_code == 401


def test_empty_portfolio(client, users, tables):  # noqa: F811
    body = _get(client, users[0])
    assert body == {
        "as_of": "2026-11-02", "overall": None, "by_class": [], "by_type": [], "best": [],
        "worst": [], "rates": [],
        "excluded": {"at_cost": 0, "no_flows": 0, "other_without_invested": 0},
    }  # fmt: skip


def test_seeded_portfolio(client, seeded, auth_engine):  # noqa: F811
    headers, _ = seeded
    Base.metadata.create_all(auth_engine, tables=[NpsNavHistory.__table__])
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            NpsNavHistory(scheme_id="SM001003", nav_date=date(2023, 12, 29), nav=D(20))
        )
        session.commit()
    body = _get(client, headers)
    assert body["as_of"] == "2026-11-02"
    # Soft-deleted rows and user B's holdings never reach the figures.
    by_type = {t["key"]: t for t in body["by_type"]}
    assert (by_type["fd"]["holdings"], by_type["fd"]["invested"]) == (4, 900000)
    assert (by_type["rd"]["holdings"], by_type["rd"]["invested"]) == (1, 5000)
    assert (by_type["stock"]["invested"], by_type["stock"]["current"]) == (27000, 33500)
    assert (by_type["bond"]["invested"], by_type["bond"]["current"]) == (41000, 41000)
    assert (by_type["gold"]["holdings"], by_type["gold"]["gain"]) == (1, 10000)
    # Cash, EPF/PPF and NPS have no flows; unpriced stock, NAV-less MF and rate-less silver are
    # at cost; both Other rows lack an invested amount.
    assert body["excluded"] == {"at_cost": 3, "no_flows": 6, "other_without_invested": 2}
    assert "cash" not in by_type and "pf" not in by_type and "other" not in by_type
    # Gold: 50,000 -> 60,000 over 1,036 days.
    assert by_type["gold"]["annualised"] is True
    assert by_type["gold"]["return_pct"] == pytest.approx((1.2 ** (365 / 1036) - 1) * 100, abs=0.01)
    # The ELSS fund has CAS transactions.
    elss = next(h for h in body["best"] + body["worst"] if h["name"].startswith("Axis ELSS"))
    expected, _, _ = mf_xirr(
        D(200), D(6000), date(2024, 6, 10), D(8000),
        [_txn(date(2023, 1, 10), "purchase", 100, 3000),
         _txn(date(2024, 6, 10), "purchase", 100, 3000)],
        TODAY,
    )  # fmt: skip
    assert elss["return_pct"] == pytest.approx(float(expected))
    assert elss["gain"] == 2000
    assert {c["key"] for c in body["by_class"]} <= {"equity", "debt", "hybrid", "gold", "other"}
    rates = {(r["type"], r["name"]): r for r in body["rates"]}
    assert rates[("pf", "Employer EPF")]["rate_pct"] == 8.25
    assert rates[("pf", "PPF")]["rate_pct"] == 7.1
    nps = [r for r in body["rates"] if r["type"] == "nps"]
    assert [r["basis"] for r in nps] == ["nav_cagr", "nav_cagr"]
    assert nps[0]["rate_pct"] == pytest.approx((1.5 ** (365 / 1036) - 1) * 100, abs=0.01)
    assert nps[1]["rate_pct"] is None
