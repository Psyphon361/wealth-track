"""Returns (XIRR) maths and GET /api/analytics/returns. The pure tests build valued items by hand
(today = 2026-11-02); the endpoint test reuses test_analytics_api's seeded portfolio."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import HoldingExit, NpsNavHistory, Stock
from app.routers import analytics_returns as returns_router
from app.services import analytics_benchmark as ab
from app.services import analytics_returns as ar
from app.services.valuation import mf_xirr, xirr
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


def test_exactly_six_months_old_is_ranked_one_day_younger_is_not():
    on_edge = _fd(1, 1000, 1100, start=date(2026, 5, 2))
    one_day_short = _fd(2, 1000, 1100, start=date(2026, 5, 3))
    out = ar.returns([_group("fd", on_edge, one_day_short)], TODAY)
    assert [h["id"] for h in out["best"] + out["worst"]] == [1]


def test_six_to_twelve_month_holding_ranks_by_xirr_but_group_stays_absolute():
    # 184 days at +10 %: yearly return (actual/365) = 1.1 ** (365 / 184) - 1
    out = ar.returns([_group("fd", _fd(1, 1000, 1100, start=date(2026, 5, 2)))], TODAY)
    expected = (1.1 ** (365 / 184) - 1) * 100
    assert float(out["best"][0]["return_pct"]) == pytest.approx(expected, abs=0.01)
    assert out["best"][0]["gain"] == D("100.00")
    fd = out["by_type"][0]
    assert (fd["return_pct"], fd["annualised"]) == (D("10.00"), False)
    assert out["overall"]["return_pct"] == D("10.00")


def test_best_worst_mix_of_seven_month_and_two_year_holdings():
    two_years = date(2024, 11, 2)
    seven_months = date(2026, 4, 2)
    items = [
        _fd(1, 1000, 1210, start=two_years),  # 10 % a year
        _fd(2, 1000, 1100, start=seven_months),  # 214 days: about 17 % a year
        _fd(3, 1000, 1050, start=seven_months),  # about 8.6 % a year
        _fd(4, 1000, 1440, start=two_years),  # 20 % a year
    ]
    out = ar.returns([_group("fd", *items)], TODAY)
    ids = [h["id"] for h in out["best"]]
    assert ids == [4, 2, 1, 3]
    assert float(out["best"][0]["return_pct"]) == pytest.approx(20, abs=0.01)
    assert float(out["best"][1]["return_pct"]) == pytest.approx(
        (1.1 ** (365 / 214) - 1) * 100, abs=0.01
    )
    assert out["worst"] == []


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


@pytest.fixture(autouse=True)
def no_benchmark_fetch(monkeypatch):
    """Endpoint tests never reach mfapi.in or the NAV tables; the benchmark is null by default."""
    monkeypatch.setattr(returns_router, "_fetch_benchmark_navs", lambda *args: None)


def _get(client, headers) -> dict:
    response = client.get("/api/analytics/returns", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_bearer(client):
    assert client.get("/api/analytics/returns").status_code == 401


def test_empty_portfolio(client, users, tables):  # noqa: F811
    body = _get(client, users[0])
    assert body == {
        "as_of": "2026-11-02", "overall": None, "benchmark": None, "by_class": [],
        "by_type": [], "best": [],
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


def test_sold_stock_and_its_sale_reach_the_figures(client, seeded, users, auth_engine):  # noqa: F811
    headers, _ = seeded
    a_id = users[1]
    before = {t["key"]: t for t in _get(client, headers)["by_type"]}["stock"]
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        sold = Stock(
            user_id=a_id, name="Sold probe", exchange="NSE", master_id=1, quantity=5,
            avg_buy_price=1000, buy_date=date(2024, 1, 1), closed_on=date(2025, 6, 1),
        )
        session.add(sold)
        session.flush()
        session.add_all(
            [
                # The sale counts; the maturity row (kind "maturity") must not.
                HoldingExit(
                    user_id=a_id, asset_type="stock", holding_id=sold.id, kind="sale",
                    exit_date=date(2025, 6, 1), quantity=5, amount=7000, cost=5000,
                    destination="none", prev_state={"full": True},
                ),
                HoldingExit(
                    user_id=a_id, asset_type="fd", holding_id=sold.id, kind="maturity",
                    exit_date=date(2025, 6, 1), amount=9999, cost=1, destination="none",
                ),
            ]
        )
        session.commit()
    after = {t["key"]: t for t in _get(client, headers)["by_type"]}["stock"]
    assert after["holdings"] == before["holdings"] + 1
    assert after["invested"] == before["invested"] + 5000
    assert after["current"] == before["current"]
    assert after["gain"] == before["gain"] + 2000


# --- Benchmark ---------------------------------------------------------------------------------

NAVS = [
    (date(2024, 1, 1), D(100)),
    (date(2025, 1, 1), D(110)),
    (date(2025, 7, 1), D(120)),
    (date(2026, 5, 30), D(120)),
    (TODAY, D(150)),
]


def test_replay_single_buy_is_xirr_of_units_at_latest_nav():
    # 1,000 buys 10 units at 100; 10 units x 150 = 1,500 today (the holding's own value is ignored).
    pct, annualised = ab.replay([(date(2024, 1, 1), D(-1000)), (TODAY, D(1800))], NAVS, TODAY)
    days = (TODAY - date(2024, 1, 1)).days
    assert annualised is True
    assert float(pct) == pytest.approx((1.5 ** (365 / days) - 1) * 100, abs=0.01)


def test_replay_redemption_sells_units_at_that_dates_nav():
    flows = [
        (date(2024, 1, 1), D(-1000)),  # 10 units
        (date(2025, 1, 1), D(-1100)),  # 10 units
        (date(2025, 7, 1), D(1200)),  # sells 10 units at 120
        (TODAY, D(999)),
    ]
    pct, annualised = ab.replay(flows, NAVS, TODAY)
    # 10 units left x 150 = 1,500 terminal.
    expected = xirr(
        [(date(2024, 1, 1), D(-1000)), (date(2025, 1, 1), D(-1100)),
         (date(2025, 7, 1), D(1200)), (TODAY, D(1500))]
    )  # fmt: skip
    assert annualised is True
    assert pct == (expected * 100).quantize(D("0.01"))


def test_replay_under_a_year_is_absolute():
    # Bought 2026-06-01 at the 2026-05-30 NAV 120: 1,000 -> 8.333 units x 150 = 1,250.
    pct, annualised = ab.replay([(date(2026, 6, 1), D(-1000)), (TODAY, D(1100))], NAVS, TODAY)
    assert (pct, annualised) == (D("25.00"), False)


def test_replay_absolute_counts_redemptions():
    flows = [(date(2026, 6, 1), D(-1000)), (date(2026, 8, 1), D(600)), (TODAY, D(1))]
    # Buys 8.3333 units at 120, sells 5 at 120 (but the flow is 600 = 5 units), 3.3333 x 150 = 500.
    pct, _ = ab.replay(flows, NAVS, TODAY)
    assert pct == D("10.00")  # (500 + 600 - 1000) / 1000


def test_replay_flow_before_first_nav_is_null():
    pct, annualised = ab.replay([(date(2023, 6, 1), D(-1000)), (TODAY, D(1800))], NAVS, TODAY)
    assert (pct, annualised) == (None, True)


def test_fd_rate_is_principal_weighted_over_active_fds():
    fds = _group(
        "fd",
        {"status": "active", "principal": D(100000), "rate": D("7")},
        {"status": "active", "principal": D(300000), "rate": D("8")},
        {"status": "matured", "principal": D(900000), "rate": D("3")},
    )
    assert ab.fd_rate([fds]) == D("7.75")
    assert ab.fd_rate([_group("fd"), _group("bond", {"status": "active"})]) is None


CPI = {2022: D(6), 2023: D(5), 2024: D(4), 2025: D(2)}


def test_inflation_compounds_from_the_since_year_to_the_latest_year():
    pct, period = ab.inflation(date(2023, 3, 1), CPI)
    assert period == "2023–2025"
    assert float(pct) == pytest.approx(((1.05 * 1.04 * 1.02) ** (1 / 3) - 1) * 100, abs=0.01)
    assert ab.inflation(date(2025, 12, 1), CPI) == (D("2.00"), "2025")


def test_inflation_clips_to_the_data_and_is_null_without_overlap():
    pct, period = ab.inflation(date(2001, 1, 1), CPI)
    assert period == "2022–2025"
    assert float(pct) == pytest.approx(((1.06 * 1.05 * 1.04 * 1.02) ** 0.25 - 1) * 100, abs=0.01)
    assert ab.inflation(date(2030, 1, 1), CPI) == (None, None)
    assert ab.inflation(None, CPI) == (None, None)


def test_cpi_seed_file_loads():
    cpi = ab.load_cpi()
    assert min(cpi) == 2013 and max(cpi) >= 2025
    assert all(D(0) < v < D(15) for v in cpi.values())


def _stock(id_, start):
    return {
        "id": id_, "name": f"S{id_}", "status": "active", "invested": D(1000),
        "current_value": D(1800), "buy_date": start, "price": D(1), "symbol": f"S{id_}",
    }  # fmt: skip


def test_benchmark_block_in_returns():
    groups = [
        _group("fd", {**_fd(1, 1000, 1100, date(2025, 1, 1)), "principal": D(1000), "rate": D(7)}),
        _group("stock", _stock(2, date(2024, 1, 1))),
    ]
    asked = []

    def loader(since):
        asked.append(since)
        return ab.BenchmarkNavs("Test Fund", NAVS)

    result = ar.returns(groups, TODAY, benchmark_loader=loader, cpi=CPI)
    assert asked == [result["overall"]["since"]]
    bench = result["benchmark"]
    assert bench["label"] == "Nifty 50 index fund" and bench["scheme_name"] == "Test Fund"
    assert bench["nav_date"] == TODAY
    assert bench["fd_rate"] == D("7.00")
    assert (bench["inflation_pct"] is not None, bench["inflation_period"]) == (True, "2024–2025")
    assert bench["overall"]["your_pct"] == result["overall"]["return_pct"]
    assert bench["overall"]["annualised"] is True
    equity = next(g for g in result["by_class"] if g["key"] == "equity")
    assert bench["equity"]["your_pct"] == equity["return_pct"]
    assert bench["equity"]["benchmark_pct"] == D("15.36")


def test_benchmark_is_null_without_loader_flows_or_navs():
    groups = [_group("stock", _stock(2, date(2024, 1, 1)))]
    assert ar.returns(groups, TODAY)["benchmark"] is None
    assert ar.returns(groups, TODAY, benchmark_loader=lambda since: None)["benchmark"] is None
    calls = []
    result = ar.returns([], TODAY, benchmark_loader=lambda since: calls.append(1))
    assert result["benchmark"] is None and not calls


def test_endpoint_returns_benchmark(client, seeded, monkeypatch):  # noqa: F811
    headers, _ = seeded
    navs = ab.BenchmarkNavs("UTI Nifty 50 Index Fund", [(date(2000, 1, 1), D(100)), (TODAY, D(300))])
    monkeypatch.setattr(returns_router, "_fetch_benchmark_navs", lambda *args: navs)
    bench = _get(client, headers)["benchmark"]
    assert bench["label"] == "Nifty 50 index fund"
    assert bench["scheme_name"] == "UTI Nifty 50 Index Fund"
    assert bench["nav_date"] == "2026-11-02"
    assert bench["fd_rate"] == 8.0
    assert bench["overall"]["benchmark_pct"] is not None
    assert bench["inflation_period"].endswith("–2025")


# --- Payout FDs: interest paid out is a cash flow on its payout date ----------------------------


def _fd_item(compounding, payout, start=date(2024, 11, 2), years=3, principal=100000, rate=8):
    from app.services.valuation import value_fd

    fd = SimpleNamespace(
        principal=D(principal), rate=D(rate), start_date=start, compounding=compounding,
        payout_type=payout, tenure_years=years, tenure_months=0, tenure_days=0,
    )  # fmt: skip
    value = value_fd(fd, TODAY)
    return {
        "id": 1, "bank": "Bank 1", "label": None, "principal": fd.principal, "rate": fd.rate,
        "start_date": start, "compounding": compounding, "payout_type": payout, **value,
    }  # fmt: skip


@pytest.mark.parametrize(
    "compounding,periods,expected_pct",
    [("quarterly", 4, 8.2432), ("monthly", 12, 8.3000)],  # (1 + 8% / n) ** n - 1, hand-computed
)
def test_payout_fd_xirr_is_the_effective_annual_rate(compounding, periods, expected_pct):
    item = _fd_item(compounding, "payout")
    built = ar.holding_flows("fd", item, TODAY)
    assert built.flows[0] == (date(2024, 11, 2), D(-100000))
    assert built.flows[-1][0] == TODAY
    payouts = built.flows[1:-1]
    assert len(payouts) + 1 == 2 * periods  # the payout falling today joins the last flow
    assert payouts[0][1] == (D(100000) * D("0.08") / periods).quantize(D("0.01"))
    out = ar.returns([_group("fd", item)], TODAY)
    assert out["overall"]["annualised"] is True
    assert abs(float(out["overall"]["return_pct"]) - expected_pct) < 0.05
    assert out["overall"]["gain"] == D(str(item["gain"])) == D(str(item["interest_received"]))


def test_payout_fd_flows_total_the_interest_received():
    item = _fd_item("quarterly", "payout")
    built = ar.holding_flows("fd", item, TODAY)
    total = sum(a for _, a in built.flows)
    assert total == D(str(item["interest_received"]))


def test_cumulative_fd_flows_unchanged():
    item = _fd_item("quarterly", "cumulative")
    built = ar.holding_flows("fd", item, TODAY)
    assert built.flows == [
        (date(2024, 11, 2), D(-100000)),
        (TODAY, D(str(item["current_value"]))),
    ]
    out = ar.returns([_group("fd", item)], TODAY)
    assert out["overall"]["gain"] == D(str(item["gain"]))


def test_bond_has_no_interest_received_so_keeps_two_flows():
    from app.services.valuation import value_bond

    bond = SimpleNamespace(
        invested_amount=D(100000), ytm=D(8), purchase_date=date(2024, 11, 2),
        maturity_date=date(2029, 11, 2),
    )  # fmt: skip
    value = value_bond(bond, TODAY)
    assert "interest_received" not in value
    item = {"id": 1, "name": "B", "status": "active", "purchase_date": bond.purchase_date, **value}
    assert len(ar.holding_flows("bond", item, TODAY).flows) == 2


def test_benchmark_replay_treats_intermediate_payouts_as_redemptions():
    rows = [(date(2000, 1, 1), D(100))]
    flows = [(date(2026, 1, 2), D(-100)), (date(2026, 5, 2), D(10)), (TODAY, D(100))]
    pct, annualised = ab.replay(flows, rows, TODAY)
    # 1 unit bought, 0.1 sold for 10, 0.9 units left worth 90: (90 + 10 - 100) / 100
    assert annualised is False and pct == D("0.00")
