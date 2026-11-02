from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Gold, GoldRateHistory, GoldRateLatest, Stock, StockPriceLatest
from app.routers.portfolio import build_dashboard, build_groups
from app.services import gold_rates, valuation
from tests.conftest import (
    make_bond, make_cash, make_fd, make_gold, make_nps, make_other, make_stock,
)
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 2)
D = Decimal


def _groups(**extra):
    """A mix of every kind of holding, valued on TODAY."""
    price = SimpleNamespace(
        price=D("110"), prev_close=D("100"), price_time=datetime(2026, 10, 30, 15, 30), source="bhavcopy"
    )
    return build_groups(
        {
            "stock": [make_stock(master_id=1)],  # 10 x (110 - 100) = +100
            "gold": [make_gold()],  # 10 g x (7000 - 6900) = +1000
            "nps": [make_nps()],  # 1000 units x (20 - 19.5) = +500
            "fd": [make_fd(start_date=date(2026, 10, 1))],
            "bond": [make_bond()],  # matured on 2026-10-24
            "cash": [make_cash()],
            **extra,
        },
        TODAY,
        prices={1: price},
        rates={("gold", "916"): (D("7000"), date(2026, 10, 30))},
        nps_navs={"SM001003": (D("20"), date(2026, 10, 29))},
        nps_prev={"SM001003": (date(2026, 10, 28), D("19.5"))},
    )


PREV = {("gold", "916"): (date(2026, 10, 29), D("6900"))}


def _change(groups, prev=PREV):
    total = build_dashboard(groups)["total_current"]
    return valuation.portfolio_day_change(groups, prev, total)


def test_mix_of_types_sums_market_linked_holdings():
    change, pct, as_of = _change(_groups())
    assert change == D("1600.00")
    assert as_of == date(2026, 10, 30)  # the latest of price, NAV and rate dates
    total = build_dashboard(_groups())["total_current"]
    assert pct == (D("1600") / (total - D("1600")) * 100).quantize(D("0.01"))


def test_matured_bond_and_fd_add_nothing():
    groups = build_groups(
        {"bond": [make_bond()], "fd": [make_fd(start_date=date(2026, 10, 1))]}, TODAY
    )
    assert _change(groups) == (None, None, None)


def test_matured_items_are_skipped_even_with_a_figure():
    groups = [
        {
            "type": "stock",
            "items": [
                {"status": "matured", "quantity": 10, "price": 110, "prev_close": 100,
                 "price_time": "2026-10-30T15:30:00+05:30"},
                {"status": "active", "quantity": 1, "price": 110, "prev_close": 100,
                 "price_time": "2026-10-30T15:30:00+05:30"},
            ],
        }
    ]  # fmt: skip
    assert valuation.portfolio_day_change(groups, {}, D("1000")) == (
        D("10.00"), D("1.01"), date(2026, 10, 30)
    )


def test_no_market_data_is_null_not_zero():
    # Stock and gold without price/rate rows, NPS without a previous NAV: nothing contributed.
    groups = build_groups(
        {"stock": [make_stock()], "gold": [make_gold()], "nps": [make_nps()], "cash": [make_cash()]},
        TODAY,
        nps_navs={"SM001003": (D("20"), date(2026, 10, 29))},
    )
    assert _change(groups, prev={}) == (None, None, None)
    assert _change(build_groups({}, TODAY), prev={}) == (None, None, None)


def test_stock_without_prev_close_or_gold_without_previous_rate_is_skipped():
    price = SimpleNamespace(price=D("110"), prev_close=None, price_time=None, source="bhavcopy")
    groups = build_groups(
        {"stock": [make_stock(master_id=1)], "gold": [make_gold()]},
        TODAY,
        prices={1: price},
        rates={("gold", "916"): (D("7000"), date(2026, 10, 30))},
    )
    assert _change(groups, prev={}) == (None, None, None)
    # A previous rate dated on or after the latest one is ignored too.
    stale = {("gold", "916"): (date(2026, 10, 30), D("6900"))}
    assert _change(groups, prev=stale) == (None, None, None)


def test_loss_is_negative_with_negative_pct():
    price = SimpleNamespace(
        price=D("90"), prev_close=D("100"), price_time=datetime(2026, 10, 30, 15, 30), source="bhavcopy"
    )
    groups = build_groups({"stock": [make_stock(master_id=1)]}, TODAY, prices={1: price})
    change, pct, _ = _change(groups, prev={})
    assert change == D("-100.00")
    assert pct == D("-10.00")  # -100 / (900 + 100)


def test_zero_change_is_a_figure_not_null():
    price = SimpleNamespace(
        price=D("100"), prev_close=D("100"), price_time=datetime(2026, 10, 30, 15, 30), source="bhavcopy"
    )
    groups = build_groups({"stock": [make_stock(master_id=1)]}, TODAY, prices={1: price})
    assert _change(groups, prev={}) == (D("0.00"), D("0.00"), date(2026, 10, 30))


def test_pct_is_null_when_denominator_not_positive():
    groups = [{"type": "nps", "items": [{"status": "active", "day_change": 500, "nav_date": "2026-10-29"}]}]
    assert valuation.portfolio_day_change(groups, {}, D("500")) == (D("500.00"), None, date(2026, 10, 29))
    assert valuation.portfolio_day_change(groups, {}, D("100"))[1] is None
    assert valuation.portfolio_day_change(groups, {}, D("501"))[1] == D("50000.00")  # 500 / (501 - 500)


# --- endpoint and the silver 925 derivation ------------------------------------------


@pytest.fixture
def market(client, auth_engine):  # noqa: F811
    Base.metadata.create_all(auth_engine, tables=[StockPriceLatest.__table__, GoldRateHistory.__table__])
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        yield session


def _rate_rows(session, *, metal="silver", purity="999"):
    session.add(
        GoldRateLatest(
            metal=metal, purity=purity, rate_per_gram=D("90"), rate_date=date(2026, 10, 30),
            session="PM", source="ibja",
        )
    )
    session.add_all(
        GoldRateHistory(metal=metal, purity=purity, rate_date=d, rate_per_gram=D(rate))
        for d, rate in [
            (date(2026, 10, 30), "90"), (date(2026, 10, 28), "88"), (date(2026, 10, 27), "80"),
        ]
    )  # fmt: skip
    session.commit()


def test_silver_925_previous_rate_is_derived_from_999(market):
    _rate_rows(market)
    prev = gold_rates.previous_rates(market, [("silver", "925"), ("silver", "999"), ("gold", "999")])
    # The latest stored date is 30 Oct, so the previous one is 28 Oct (no row for 29 Oct).
    assert prev == {
        ("silver", "925"): (date(2026, 10, 28), D("81.48")),  # 88 x 925 / 999
        ("silver", "999"): (date(2026, 10, 28), D("88.00")),
    }
    assert gold_rates.previous_rates(market, []) == {}


def test_dashboard_has_null_fields_without_holdings(client, users, market):  # noqa: F811
    body = client.get("/api/dashboard", headers=users[0]).json()
    assert body["day_change"] is None
    assert body["day_change_pct"] is None
    assert body["day_change_as_of"] is None


def test_dashboard_day_change_excludes_soft_deleted_and_derives_silver_925(client, users, market):  # noqa: F811
    headers, user_id = users[0], users[1]
    _rate_rows(market)
    market.add_all(
        [
            StockPriceLatest(
                master_id=1, price=D("110"), prev_close=D("100"),
                price_time=datetime(2026, 10, 30, 15, 30), source="bhavcopy",
            ),
            StockPriceLatest(
                master_id=2, price=D("50"), prev_close=D("40"),
                price_time=datetime(2026, 10, 30, 15, 30), source="bhavcopy",
            ),
            Stock(
                user_id=user_id, name="Live", exchange="NSE", master_id=1, quantity=10,
                avg_buy_price=D("100"), buy_date=date(2025, 1, 1),
            ),
            Stock(
                user_id=user_id, name="Gone", exchange="NSE", master_id=2, quantity=100,
                avg_buy_price=D("40"), buy_date=date(2025, 1, 1),
                deleted_at=datetime(2026, 10, 31),
            ),
            Gold(
                user_id=user_id, name="Silver", form="coin", metal="silver", purity="925",
                weight_grams=D("100"), purchase_date=date(2025, 1, 1), invested_amount=D("7000"),
            ),
        ]
    )  # fmt: skip
    market.commit()

    body = client.get("/api/dashboard", headers=headers).json()
    # Stock: 10 x (110 - 100) = 100. Silver 925: 100 g x (83.33 - 81.48) = 185.
    # The soft-deleted stock would add 1000.
    assert body["day_change"] == 285.0
    assert body["day_change_as_of"] == "2026-10-30"
    assert body["day_change_pct"] == pytest.approx(
        285 / (body["total_current"] - 285) * 100, abs=0.01
    )


# --- per-type rows on the dashboard ------------------------------------------------------


def _rows(groups, prev=PREV):
    from app.routers.portfolio import add_day_change

    out = add_day_change(build_dashboard(groups), groups, prev)
    return out, {r["type"]: r for r in out["by_type"]}


def test_per_type_day_changes_add_up_to_total():
    out, rows = _rows(_groups())
    assert rows["stock"]["day_change"] == D("100.00")
    assert rows["gold"]["day_change"] == D("1000.00")
    assert rows["nps"]["day_change"] == D("500.00")
    parts = [r["day_change"] for r in rows.values() if r["day_change"] is not None]
    assert abs(sum(parts) - out["day_change"]) <= D("0.01") * len(parts)


def test_type_without_market_data_has_null_day_change():
    _, rows = _rows(build_groups({"stock": [make_stock()], "cash": [make_cash()]}, TODAY), prev={})
    assert rows["stock"]["day_change"] is None
    assert rows["cash"]["day_change"] is None


def test_fd_has_gain_but_no_day_change():
    _, rows = _rows(_groups())
    assert rows["fd"]["day_change"] is None
    assert rows["fd"]["gain"] is not None
    assert rows["fd"]["gain_pct"] is not None


def test_empty_type_has_null_gain():
    _, rows = _rows(_groups())
    assert rows["rd"]["count"] == 0
    assert rows["rd"]["gain"] is None
    assert rows["rd"]["gain_pct"] is None


def test_other_without_invested_has_no_gain_but_with_invested_has():
    _, rows = _rows(build_groups({"other": [make_other()]}, TODAY), prev={})
    assert rows["other"]["current"] == D("80000.00")
    assert rows["other"]["gain"] is None
    assert rows["other"]["gain_pct"] is None
    _, rows = _rows(
        build_groups({"other": [make_other(invested_amount=D("50000"))]}, TODAY), prev={}
    )
    assert rows["other"]["gain"] == D("30000.00")
