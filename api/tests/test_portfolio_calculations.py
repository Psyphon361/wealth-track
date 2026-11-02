"""Portfolio and dashboard totals plus small valuation gaps.

Every expected figure is worked out by hand and written as a literal. All date spans stay
between 2025-01-01 and 2027-12-31.
"""

from datetime import date, datetime
from decimal import Decimal
from itertools import count
from types import SimpleNamespace

from app.routers import holdings
from app.routers.portfolio import build_dashboard, build_groups
from app.services import gold_rates, valuation
from tests.conftest import (
    make_bond, make_cash, make_fd, make_gold, make_nps, make_other, make_pf, make_stock,
)  # fmt: skip

D = Decimal
TODAY = date(2026, 11, 2)
_STAMP = datetime(2025, 1, 1)
_ids = count(50_000)


def make_rd(**kw):
    fields = dict(
        bank="Test Bank", issuer_id=None, label=None, monthly_instalment=D("1000"), rate=D("0"),
        start_date=date(2026, 10, 3), compounding="simple", tenure_years=1, tenure_months=0,
        tenure_days=0,
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(
        id=next(_ids), created_at=_STAMP, updated_at=_STAMP, notes=None, **fields
    )


def make_mf(**kw):
    fields = dict(
        scheme_name="Test Fund", scheme_code=100, platform=None, category="equity",
        units=D("100"), avg_nav=D("100"), invested_amount=D("10000"),
        purchase_date=date(2025, 10, 24),
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(
        id=next(_ids), created_at=_STAMP, updated_at=_STAMP, notes=None, **fields
    )


def _price(price, prev_close="100", when=datetime(2026, 10, 30, 15, 30)):
    return SimpleNamespace(
        price=D(price), prev_close=D(prev_close), price_time=when, source="bhavcopy"
    )


def _group(groups, slug):
    return next(g for g in groups if g["type"] == slug)


def _row(dash, slug):
    return next(r for r in dash["by_type"] if r["type"] == slug)


# --- aggregate ----------------------------------------------------------------------------


def test_aggregate_empty_is_all_zero():
    assert valuation.aggregate([]) == {
        "invested": D("0.00"), "current_value": D("0.00"), "gain": D("0.00"),
        "gain_pct": D("0.00"), "gain_base": D("0.00"),
    }  # fmt: skip


def test_aggregate_zero_invested_gives_zero_gain_pct():
    out = valuation.aggregate(
        [{"invested": D("0.00"), "current_value": D("50.00"), "gain": D("50.00")}]
    )
    assert out["invested"] == D("0.00")
    assert out["current_value"] == D("50.00")
    assert out["gain"] == D("50.00")
    assert out["gain_pct"] == D("0.00")


def test_aggregate_fractional_amounts():
    out = valuation.aggregate(
        [
            {"invested": D("1000.10"), "current_value": D("1100.25"), "gain": D("100.15")},
            {"invested": D("333.33"), "current_value": D("300.10"), "gain": D("-33.23")},
            {"invested": D("0.05"), "current_value": D("0.07"), "gain": D("0.02")},
        ]
    )
    assert out == {
        "invested": D("1333.48"),
        "current_value": D("1400.42"),
        "gain": D("66.94"),
        "gain_pct": D("5.02"),  # 66.94 / 1333.48 = 5.0199 %
        "gain_base": D("1333.48"),  # every result has a gain
    }


def _other_mix():
    """Other A: worth 100, no invested amount (no gain). Other B: worth 150, 100 invested."""
    return [
        make_other(current_value=D("100"), invested_amount=None),
        make_other(current_value=D("150"), invested_amount=D("100")),
    ]


def test_aggregate_gain_pct_ignores_holdings_without_a_gain():
    results = [valuation.value_other(o, TODAY) for o in _other_mix()]
    assert valuation.aggregate(results) == {
        "invested": D("200.00"), "current_value": D("250.00"), "gain": D("50.00"),
        "gain_pct": D("50.00"),  # 50 / 100 (only B has a gain), not 50 / 200 = 25 %
        "gain_base": D("100.00"),
    }  # fmt: skip


# --- build_groups: totals per type --------------------------------------------------------


def test_rd_group_totals_and_matured_count():
    active = make_rd(rate=D("36.5"))  # one instalment of 1000 on 3 Oct, 30 days at 36.5 % simple
    matured = make_rd(start_date=date(2025, 1, 1), tenure_years=0, tenure_months=3)
    group = _group(build_groups({"rd": [active, matured]}, TODAY), "rd")
    assert group["count"] == 1
    assert group["matured_count"] == 1
    assert [i["status"] for i in group["items"]] == ["active", "matured"]
    assert group["totals"] == {
        "invested": D("1000.00"), "current_value": D("1030.00"), "gain": D("30.00"),
        "gain_pct": D("3.00"), "gain_base": D("1000.00"),
    }  # fmt: skip


def test_bond_group_totals_and_matured_count():
    active = make_bond(
        purchase_date=date(2025, 11, 2), maturity_date=date(2027, 11, 2), ytm=D("10")
    )  # exactly 365 days at 10 %: 10000 -> 11000
    group = _group(build_groups({"bond": [active, make_bond()]}, TODAY), "bond")
    assert group["count"] == 1
    assert group["matured_count"] == 1  # the default bond matured on 2026-10-24
    assert group["totals"] == {
        "invested": D("10000.00"), "current_value": D("11000.00"), "gain": D("1000.00"),
        "gain_pct": D("10.00"), "gain_base": D("10000.00"),
    }  # fmt: skip


def test_mf_group_totals_at_latest_nav():
    a = make_mf(scheme_code=100, units=D("100"), invested_amount=D("10000"))  # 100 x 120.5
    b = make_mf(scheme_code=200, units=D("40"), invested_amount=D("4000"))  # 40 x 90.2
    navs = {100: (D("120.5"), date(2026, 10, 30)), 200: (D("90.2"), date(2026, 10, 30))}
    group = _group(build_groups({"mf": [a, b]}, TODAY, navs=navs), "mf")
    assert group["count"] == 2
    assert group["matured_count"] == 0
    assert group["totals"] == {
        "invested": D("14000.00"), "current_value": D("15658.00"), "gain": D("1658.00"),
        "gain_pct": D("11.84"), "gain_base": D("14000.00"),
    }  # fmt: skip


def test_nps_group_totals_at_latest_nav():
    a = make_nps()  # 1000 units, 40000 contributed
    b = make_nps(units=D("200"), contributed=D("8000"))
    nav = {"SM001003": (D("45.5"), date(2026, 10, 30))}
    group = _group(build_groups({"nps": [a, b]}, TODAY, nps_navs=nav), "nps")
    assert group["count"] == 2
    assert group["matured_count"] == 0
    assert group["totals"] == {
        "invested": D("48000.00"), "current_value": D("54600.00"), "gain": D("6600.00"),
        "gain_pct": D("13.75"), "gain_base": D("48000.00"),
    }  # fmt: skip


def test_gold_group_totals_for_gold_and_silver():
    gold = make_gold()  # 10 g of 916 at 6000 = 60000, invested 50000
    silver = make_gold(
        metal="silver", purity="999", weight_grams=D("100"), invested_amount=D("7000")
    )  # 100 g at 90 = 9000
    rates = {
        ("gold", "916"): (D("6000"), date(2026, 10, 30)),
        ("silver", "999"): (D("90"), date(2026, 10, 30)),
    }
    group = _group(build_groups({"gold": [gold, silver]}, TODAY, rates=rates), "gold")
    assert group["count"] == 2
    assert group["matured_count"] == 0
    assert group["totals"] == {
        "invested": D("57000.00"), "current_value": D("69000.00"), "gain": D("12000.00"),
        "gain_pct": D("21.05"), "gain_base": D("57000.00"),
    }  # fmt: skip


def test_cash_group_totals_have_no_gain():
    cash = [make_cash(), make_cash(balance=D("1234.56"))]
    group = _group(build_groups({"cash": cash}, TODAY), "cash")
    assert group["count"] == 2
    assert group["matured_count"] == 0
    assert group["totals"] == {
        "invested": D("26234.56"), "current_value": D("26234.56"), "gain": D("0.00"),
        "gain_pct": D("0.00"), "gain_base": D("26234.56"),
    }  # fmt: skip


def test_pf_group_totals_with_and_without_contributions():
    accruing = make_pf(
        balance=D("100000"), interest_rate=D("7.3"), balance_date=date(2026, 10, 3),
        contributed=D("80000"),
    )  # 30 days of 7.3 % simple on 100000 = 600.00
    fresh = make_pf(
        balance=D("50000"), interest_rate=D("7.1"), balance_date=TODAY, contributed=None
    )  # no days accrued; invested falls back to current
    group = _group(build_groups({"pf": [accruing, fresh]}, TODAY), "pf")
    assert group["count"] == 2
    assert group["matured_count"] == 0
    assert group["totals"] == {
        "invested": D("130000.00"), "current_value": D("150600.00"), "gain": D("20600.00"),
        "gain_pct": D("15.85"), "gain_base": D("130000.00"),
    }  # fmt: skip


# --- build_groups: fallbacks and prices_as_of ---------------------------------------------


def test_stock_without_master_id_or_price_falls_back_to_invested():
    no_master = make_stock(master_id=None)
    no_price_row = make_stock(master_id=5)
    groups = build_groups({"stock": [no_master, no_price_row]}, TODAY, prices={1: _price("150")})
    stock = _group(groups, "stock")
    assert stock["totals"] == {
        "invested": D("2000.00"), "current_value": D("2000.00"), "gain": D("0.00"),
        "gain_pct": D("0.00"), "gain_base": D("2000.00"),
    }  # fmt: skip
    assert [i["current_value"] for i in stock["items"]] == [1000.0, 1000.0]
    assert [i["price"] for i in stock["items"]] == [None, None]
    assert stock["prices_as_of"] is None


def test_stock_prices_as_of_is_the_newest_price_time():
    prices = {
        1: _price("125.5", when=datetime(2026, 10, 29, 15, 30)),  # 10 x 125.5 = 1255
        2: _price("90", when=datetime(2026, 10, 30, 15, 30)),  # 10 x 90 = 900
    }
    stocks = [make_stock(master_id=1), make_stock(master_id=2), make_stock()]  # last: unpriced
    stock = _group(build_groups({"stock": stocks}, TODAY, prices=prices), "stock")
    assert stock["prices_as_of"] == datetime(2026, 10, 30, 15, 30)
    assert stock["totals"] == {
        "invested": D("3000.00"), "current_value": D("3155.00"), "gain": D("155.00"),
        "gain_pct": D("5.17"), "gain_base": D("3000.00"),
    }  # fmt: skip
    assert stock["items"][0]["price_time"] == "2026-10-29T15:30:00"


def test_stock_prices_as_of_is_none_when_prices_have_no_time():
    stock = _group(
        build_groups(
            {"stock": [make_stock(master_id=1)]}, TODAY, prices={1: _price("120", when=None)}
        ),
        "stock",
    )
    assert stock["items"][0]["current_value"] == 1200.0  # still valued at the price
    assert stock["items"][0]["price_time"] is None
    assert stock["prices_as_of"] is None


def test_mf_without_nav_falls_back_to_invested():
    with_code = make_mf(scheme_code=100, invested_amount=D("10000"))  # no NAV row for it
    no_code = make_mf(scheme_code=None, units=D("40"), invested_amount=D("4000"))
    mf = _group(build_groups({"mf": [with_code, no_code]}, TODAY, navs={}), "mf")
    assert mf["totals"] == {
        "invested": D("14000.00"), "current_value": D("14000.00"), "gain": D("0.00"),
        "gain_pct": D("0.00"), "gain_base": D("14000.00"),
    }  # fmt: skip
    assert [i["nav"] for i in mf["items"]] == [None, None]
    assert [i["nav_date"] for i in mf["items"]] == [None, None]


def test_gold_without_matching_rate_falls_back_to_invested():
    rates = {("gold", "999"): (D("7000"), date(2026, 10, 30))}  # none for 916
    gold = _group(build_groups({"gold": [make_gold()]}, TODAY, rates=rates), "gold")
    assert gold["totals"] == {
        "invested": D("50000.00"), "current_value": D("50000.00"), "gain": D("0.00"),
        "gain_pct": D("0.00"), "gain_base": D("50000.00"),
    }  # fmt: skip
    assert gold["items"][0]["rate_per_gram"] is None
    assert gold["items"][0]["rate_date"] is None


# --- build_dashboard ----------------------------------------------------------------------


def test_dashboard_with_no_groups():
    assert build_dashboard([]) == {
        "total_invested": D("0.00"), "total_current": D("0.00"), "total_gain": D("0.00"),
        "gain_pct": D("0.00"), "by_type": [],
    }  # fmt: skip


def test_dashboard_with_all_groups_empty_is_all_zero():
    dash = build_dashboard(build_groups({}, TODAY))
    assert dash["total_invested"] == D("0.00")
    assert dash["total_current"] == D("0.00")
    assert dash["total_gain"] == D("0.00")
    assert dash["gain_pct"] == D("0.00")
    assert len(dash["by_type"]) == 10
    for row in dash["by_type"]:
        assert row["count"] == 0
        assert row["matured_count"] == 0
        assert row["invested"] == D("0.00")
        assert row["current"] == D("0.00")
        assert row["allocation_pct"] == D("0.00")
        assert row["gain"] is None
        assert row["gain_pct"] is None


def test_dashboard_total_current_zero_has_zero_allocation():
    groups = build_groups(
        {"stock": [make_stock(master_id=1)]}, TODAY, prices={1: _price("0")}
    )  # worthless stock: 1000 invested, 0 now
    dash = build_dashboard(groups)
    assert dash["total_invested"] == D("1000.00")
    assert dash["total_current"] == D("0.00")
    assert dash["total_gain"] == D("-1000.00")
    assert dash["gain_pct"] == D("-100.00")
    stock = _row(dash, "stock")
    assert stock["allocation_pct"] == D("0.00")
    assert stock["gain"] == D("-1000.00")
    assert stock["gain_pct"] == D("-100.00")


def test_dashboard_total_invested_zero_has_zero_gain_pct():
    mf = make_mf(units=D("10"), invested_amount=D("0"))  # 10 units at NAV 5 = 50, nothing invested
    groups = build_groups({"mf": [mf]}, TODAY, navs={100: (D("5"), date(2026, 10, 30))})
    dash = build_dashboard(groups)
    assert dash["total_invested"] == D("0.00")
    assert dash["total_current"] == D("50.00")
    assert dash["total_gain"] == D("50.00")
    assert dash["gain_pct"] == D("0.00")
    row = _row(dash, "mf")
    assert row["gain"] == D("50.00")
    assert row["gain_pct"] == D("0.00")
    assert row["allocation_pct"] == D("100.00")


def test_dashboard_allocation_three_types_rounds_down_to_99_99():
    groups = build_groups(
        {
            "cash": [make_cash(balance=D("10000"))],
            "other": [make_other(current_value=D("10000"))],
            "stock": [make_stock(quantity=100)],  # no price: 100 x 100 invested
        },
        TODAY,
    )
    dash = build_dashboard(groups)
    assert dash["total_current"] == D("30000.00")
    assert _row(dash, "cash")["allocation_pct"] == D("33.33")
    assert _row(dash, "other")["allocation_pct"] == D("33.33")
    assert _row(dash, "stock")["allocation_pct"] == D("33.33")
    total = sum(r["allocation_pct"] for r in dash["by_type"])
    assert total == D("99.99")
    assert abs(total - D("100")) <= D("0.03")


def test_dashboard_allocation_seven_types_rounds_up_to_100_03():
    groups = build_groups(
        {
            "cash": [make_cash(balance=D("1000"))],
            "other": [make_other(current_value=D("1000"))],
            "stock": [make_stock()],  # 10 x 100 invested
            "gold": [make_gold(invested_amount=D("1000"))],  # no rate: invested
            "mf": [make_mf(scheme_code=None, units=D("10"), invested_amount=D("1000"))],
            "nps": [make_nps(contributed=D("1000"))],  # no NAV: contributed
            "pf": [
                make_pf(balance=D("1000"), interest_rate=D("0"), balance_date=TODAY)
            ],
        },
        TODAY,
    )
    dash = build_dashboard(groups)
    assert dash["total_current"] == D("7000.00")
    for slug in ("cash", "other", "stock", "gold", "mf", "nps", "pf"):
        assert _row(dash, slug)["allocation_pct"] == D("14.29")
    total = sum(r["allocation_pct"] for r in dash["by_type"])
    assert total == D("100.03")
    assert abs(total - D("100")) <= D("0.03")


def test_dashboard_matured_only_types_have_null_gain_and_stay_out_of_totals():
    groups = build_groups(
        {
            "fd": [make_fd(start_date=date(2025, 1, 1))],  # matured 2026-01-01
            "bond": [make_bond()],  # matured 2026-10-24
            "cash": [make_cash()],
        },
        TODAY,
    )
    dash = build_dashboard(groups)
    assert dash["total_invested"] == D("25000.00")
    assert dash["total_current"] == D("25000.00")
    assert dash["total_gain"] == D("0.00")
    assert dash["gain_pct"] == D("0.00")
    for slug in ("fd", "bond"):
        row = _row(dash, slug)
        assert row["count"] == 0
        assert row["matured_count"] == 1
        assert row["invested"] == D("0.00")
        assert row["current"] == D("0.00")
        assert row["gain"] is None
        assert row["gain_pct"] is None
        assert row["allocation_pct"] == D("0.00")
    cash = _row(dash, "cash")
    assert cash["gain"] == D("0.00")
    assert cash["gain_pct"] == D("0.00")
    assert cash["allocation_pct"] == D("100.00")


# --- holdings summary ---------------------------------------------------------------------


def _summary(monkeypatch, group):
    monkeypatch.setattr(holdings, "load_group", lambda db, slug, user_id: group)
    return holdings._run(
        None, 1, "stock", q=None, sort="current_value", dir="desc", page=1, multi={}
    )["summary"]


def test_holdings_summary_with_zero_invested(monkeypatch):
    free_shares = make_stock(master_id=1, avg_buy_price=D("0"))  # 10 shares at price 12 = 120
    group = _group(
        build_groups(
            {"stock": [free_shares]}, TODAY, prices={1: _price("12", prev_close="11")}
        ),
        "stock",
    )
    assert _summary(monkeypatch, group) == {
        "count": 1, "matured_count": 0, "invested": D("0.00"), "current_value": D("120.00"),
        "gain": D("120.00"), "gain_pct": D("0.00"),
    }  # fmt: skip


def test_holdings_summary_of_an_empty_type(monkeypatch):
    group = _group(build_groups({}, TODAY), "stock")
    assert _summary(monkeypatch, group) == {
        "count": 0, "matured_count": 0, "invested": D("0.00"), "current_value": D("0.00"),
        "gain": D("0.00"), "gain_pct": D("0.00"),
    }  # fmt: skip


def test_holdings_summary_gain_pct_ignores_rows_without_a_gain(monkeypatch):
    group = _group(build_groups({"other": _other_mix()}, TODAY), "other")
    assert _summary(monkeypatch, group) == {
        "count": 2, "matured_count": 0, "invested": D("200.00"), "current_value": D("250.00"),
        "gain": D("50.00"), "gain_pct": D("50.00"),
    }  # fmt: skip


# --- dashboard gain % base ----------------------------------------------------------------


def test_dashboard_gain_pct_ignores_other_holdings_without_a_gain():
    fd = make_fd(
        rate=D("7.3"), start_date=date(2026, 5, 2), compounding="simple"
    )  # 184 days of 7.3 % simple on 100000 = 3680.00
    dash = build_dashboard(build_groups({"fd": [fd], "other": _other_mix()}, TODAY))
    assert dash["total_invested"] == D("100200.00")  # displayed totals still count A's 100
    assert dash["total_current"] == D("103930.00")
    assert dash["total_gain"] == D("3730.00")
    assert dash["gain_pct"] == D("3.73")  # 3730 / 100100, not 3730 / 100200 = 3.72 %
    fd_row, other_row = _row(dash, "fd"), _row(dash, "other")
    assert fd_row["gain_pct"] == D("3.68") and fd_row["gain_base"] == D("100000.00")
    assert other_row["invested"] == D("200.00")
    assert other_row["gain"] == D("50.00")
    assert other_row["gain_pct"] == D("50.00")  # not 25 %
    assert other_row["gain_base"] == D("100.00")


def test_dashboard_with_only_other_without_invested_has_no_gain():
    other = make_other(current_value=D("100"), invested_amount=None)
    dash = build_dashboard(build_groups({"other": [other]}, TODAY))
    row = _row(dash, "other")
    assert row["invested"] == D("100.00")
    assert row["gain"] is None
    assert row["gain_pct"] is None
    assert row["gain_base"] == D("0.00")
    assert dash["total_invested"] == D("100.00")
    assert dash["total_gain"] == D("0.00")
    assert dash["gain_pct"] == D("0.00")


# --- value_mf -----------------------------------------------------------------------------

MF = SimpleNamespace(scheme_code=100, units=D("10"), invested_amount=D("1000"))
NAV_DATE = date(2026, 10, 30)
PREV_DATE = date(2026, 10, 29)


def test_mf_day_change_with_a_valid_previous_nav():
    out = valuation.value_mf(
        MF, TODAY, nav=D("120"), nav_date=NAV_DATE, prev_nav=D("100"), prev_nav_date=PREV_DATE
    )
    assert out["current_value"] == D("1200.00")
    assert out["day_change"] == D("200.00")  # 10 x (120 - 100)
    assert out["day_change_pct"] == D("20.00")


def test_mf_zero_previous_nav_gives_no_day_change():
    out = valuation.value_mf(
        MF, TODAY, nav=D("120"), nav_date=NAV_DATE, prev_nav=D("0"), prev_nav_date=PREV_DATE
    )
    assert out["current_value"] == D("1200.00")
    assert out["prev_nav"] == D("0.0000")
    assert out["prev_nav_date"] == PREV_DATE
    assert out["day_change"] is None
    assert out["day_change_pct"] is None


def test_mf_negative_previous_nav_gives_no_day_change():
    out = valuation.value_mf(
        MF, TODAY, nav=D("120"), nav_date=NAV_DATE, prev_nav=D("-5"), prev_nav_date=PREV_DATE
    )
    assert out["current_value"] == D("1200.00")
    assert out["prev_nav"] == D("-5.0000")
    assert out["day_change"] is None
    assert out["day_change_pct"] is None


def test_mf_previous_nav_without_latest_nav_gives_no_day_change():
    out = valuation.value_mf(MF, TODAY, prev_nav=D("100"), prev_nav_date=PREV_DATE)
    assert out["current_value"] == D("1000.00")  # valued at invested
    assert out["nav"] is None
    assert out["day_change"] is None
    assert out["day_change_pct"] is None
    # The helper itself keeps the previous NAV but cannot compute a change without a latest one.
    assert valuation._mf_day_change(D("10"), None, D("100"), PREV_DATE) == {
        "prev_nav": D("100.0000"), "prev_nav_date": PREV_DATE, "day_change": None,
        "day_change_pct": None,
    }  # fmt: skip


def test_mf_without_scheme_code_ignores_nav():
    unlinked = SimpleNamespace(scheme_code=None, units=D("10"), invested_amount=D("1000"))
    out = valuation.value_mf(unlinked, TODAY, nav=D("120"), nav_date=NAV_DATE)
    assert out["current_value"] == D("1000.00")
    assert out["nav"] is None
    assert out["day_change"] is None


# --- value_gold ---------------------------------------------------------------------------


def test_silver_999_valued_at_its_rate():
    silver = make_gold(
        metal="silver", purity="999", weight_grams=D("100"), invested_amount=D("7000"),
        purchase_date=date(2025, 11, 2),
    )
    out = valuation.value_gold(silver, TODAY, rate=D("90"), rate_date=NAV_DATE)
    assert out["current_value"] == D("9000.00")  # 100 g x 90
    assert out["gain"] == D("2000.00")
    assert out["gain_pct"] == D("28.57")
    assert out["rate_per_gram"] == D("90.00")
    assert out["rate_date"] == NAV_DATE
    assert out["xirr"] == D("28.57")  # 365 days: the same as the plain gain


def test_silver_925_valued_at_the_derived_rate():
    # 90 x 925 / 999 = 83.33 per gram (silver 925 is derived from the 999 rate).
    assert gold_rates._scaled("silver", "925", D("90")) == D("83.33")
    assert gold_rates._scaled("silver", "999", D("90")) == D("90")
    silver = make_gold(
        metal="silver", purity="925", weight_grams=D("100"), invested_amount=D("7000"),
        purchase_date=date(2025, 11, 2),
    )
    out = valuation.value_gold(silver, TODAY, rate=D("83.33"), rate_date=NAV_DATE)
    assert out["current_value"] == D("8333.00")  # 100 g x 83.33
    assert out["gain"] == D("1333.00")
    assert out["gain_pct"] == D("19.04")
    assert out["rate_per_gram"] == D("83.33")
    assert out["xirr"] == D("19.04")


def test_gold_xirr_is_none_when_bought_today():
    gold = make_gold(purchase_date=TODAY)
    with_rate = valuation.value_gold(gold, TODAY, rate=D("6000"), rate_date=NAV_DATE)
    assert with_rate["current_value"] == D("60000.00")
    assert with_rate["xirr"] is None
    without_rate = valuation.value_gold(gold, TODAY)
    assert without_rate["current_value"] == D("50000.00")
    assert without_rate["xirr"] is None


def test_gold_loss_is_negative_gain_and_pct():
    gold = make_gold(purchase_date=date(2025, 11, 2))  # 10 g, 50000 invested
    out = valuation.value_gold(gold, TODAY, rate=D("4500"), rate_date=NAV_DATE)
    assert out["current_value"] == D("45000.00")
    assert out["gain"] == D("-5000.00")
    assert out["gain_pct"] == D("-10.00")
    assert out["xirr"] == D("-10.00")


# --- xirr ---------------------------------------------------------------------------------

START = date(2025, 1, 1)
YEAR_LATER = date(2026, 1, 1)  # 365 days


def test_xirr_total_loss_beyond_the_lower_bound_is_none():
    # 10000 -> 0.01 in a year would need -99.9999 %, below the -99.99 % search floor.
    assert valuation.xirr([(START, D("-10000")), (YEAR_LATER, D("0.01"))]) is None


def test_xirr_gain_beyond_the_upper_bound_is_none():
    # 1 -> 1,000,000 in a year would need +99,999,900 %, above the +10,000 % ceiling.
    assert valuation.xirr([(START, D("-1")), (YEAR_LATER, D("1000000"))]) is None


def test_xirr_without_a_sign_change_is_none():
    assert valuation.xirr([(START, D("100")), (YEAR_LATER, D("200"))]) is None
    assert valuation.xirr([(START, D("0")), (YEAR_LATER, D("0"))]) is None


def test_xirr_falls_back_to_bisection_when_newton_leaves_the_range():
    # 1000 -> 12 in a year: the root is -98.8 %. Newton's first step from 10 % lands far below
    # -99.99 %, so the answer comes from the bisection fallback.
    rate = valuation.xirr([(START, D("-1000")), (YEAR_LATER, D("12"))])
    assert round(float(rate), 6) == -0.988
