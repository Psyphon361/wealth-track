"""The net worth history's computed "today" point vs the dashboard totals (audit #15).

build_history overwrites its last point with the dashboard totals, which hides any drift between
the history maths and the dashboard valuation. Here the history is built for TODAY + 1 day, so
TODAY is an interior point that is NOT overwritten, and it is compared with build_dashboard.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.routers.portfolio import build_dashboard, build_groups
from app.services import networth
from tests.conftest import make_bond, make_fd, make_gold, make_stock

TODAY = date(2026, 11, 2)
D = Decimal


def make_mf(**kw):
    fields = dict(
        id=900, scheme_name="Test Fund", scheme_code=100, category="equity", units=D("10"),
        avg_nav=D("100"), invested_amount=D("1000"), purchase_date=date(2026, 1, 1),
        notes=None, created_at=datetime(2025, 1, 1), updated_at=datetime(2025, 1, 1),
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(**fields)


def _dashboard(records, **latest):
    totals = build_dashboard(build_groups(records, TODAY, **latest))
    return totals["total_invested"], totals["total_current"]


def _history_today(records, *, navs=None, closes=None, gold_rates=None):
    """History point for TODAY, not overwritten (the series ends on TODAY + 1)."""
    result = networth.build_history(
        "1m", TODAY + timedelta(days=1), records, navs or {}, closes or {}, {},
        (D(0), D(0)), gold_rates or {},
    )  # fmt: skip
    p = next(p for p in result["points"] if p["date"] == TODAY.isoformat())
    return p["invested"], p["current"]


def _price(value):
    return SimpleNamespace(
        price=D(value), prev_close=None, price_time=datetime(2026, 11, 2, 15, 30), source="bhavcopy"
    )


def _case_a():
    records = {
        "fd": [make_fd(start_date=date(2026, 6, 1))],
        "stock": [make_stock(master_id=1, quantity=10, avg_buy_price=D("100"),
                             buy_date=date(2026, 1, 1))],
        "mf": [make_mf()],
        "gold": [make_gold(purchase_date=date(2026, 1, 1), weight_grams=D("10"),
                           invested_amount=D("50000"))],
        "bond": [make_bond(purchase_date=date(2026, 3, 1), maturity_date=date(2027, 3, 1))],
    }  # fmt: skip
    return records


def test_today_point_agrees_with_dashboard_all_priced():
    records = _case_a()
    dash = _dashboard(
        records,
        prices={1: _price("150")},
        navs={100: (D("120"), TODAY)},
        rates={("gold", "916"): (D("6000"), TODAY)},
    )
    hist = _history_today(
        records,
        navs={100: [(TODAY, D("120"))]},
        closes={1: [(TODAY, D("150"))]},
        gold_rates={("gold", "916"): [(TODAY, D("6000"))]},
    )
    print("A all priced: history", hist, "dashboard", dash)
    assert hist == dash


@pytest.mark.xfail(
    strict=True,
    reason="Drift #15: history ignores a gold rate older than 7 days (values at cost) while the "
    "dashboard keeps using the latest rate at any age.",
)
def test_today_point_agrees_when_gold_rate_is_older_than_seven_days():
    records = {"gold": [make_gold(purchase_date=date(2026, 1, 1), weight_grams=D("10"),
                                  invested_amount=D("50000"))]}  # fmt: skip
    old = TODAY - timedelta(days=20)
    dash = _dashboard(records, rates={("gold", "916"): (D("6000"), old)})
    hist = _history_today(records, gold_rates={("gold", "916"): [(old, D("6000"))]})
    print("B stale gold: history", hist, "dashboard", dash, "drift", dash[1] - hist[1])
    assert hist == dash


def test_today_point_agrees_for_stock_without_price():
    records = {"stock": [make_stock(master_id=1, quantity=10, avg_buy_price=D("100"),
                                    buy_date=date(2026, 1, 1))]}  # fmt: skip
    dash = _dashboard(records)
    hist = _history_today(records)
    print("C unpriced stock: history", hist, "dashboard", dash)
    assert hist == dash


@pytest.mark.xfail(
    strict=True,
    reason="Drift #15: a stock with a latest price but no stored history close is valued at "
    "cost by the history and at the latest price by the dashboard.",
)
def test_today_point_agrees_for_stock_with_latest_price_but_no_history():
    records = {"stock": [make_stock(master_id=1, quantity=10, avg_buy_price=D("100"),
                                    buy_date=date(2026, 1, 1))]}  # fmt: skip
    dash = _dashboard(records, prices={1: _price("150")})
    hist = _history_today(records)
    print("C2 priced, no history: history", hist, "dashboard", dash, "drift", dash[1] - hist[1])
    assert hist == dash
