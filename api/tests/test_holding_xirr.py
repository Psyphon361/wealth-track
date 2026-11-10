"""Per-holding XIRR on the FD, RD, stock, bond and Other grids and detail pages (SQLite)."""

import itertools
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import HoldingExit, Stock, StockMaster, StockPriceLatest
from app.routers import holdings as holdings_router
from app.services import analytics_returns, valuation
from tests.test_exits_api import BOND, FD, GOLD, OTHER, RD, STOCK, add, item, sell
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

MASTER_ID = 8
NAMES = itertools.count(1)


def ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


@pytest.fixture
def priced(client, auth_engine):  # noqa: F811
    """Client with a latest close of 80 for stock master 8."""
    Base.metadata.create_all(auth_engine, tables=[StockMaster.__table__, StockPriceLatest.__table__])
    with sessionmaker(bind=auth_engine)() as s:
        s.add(StockMaster(id=MASTER_ID, isin="INE000A01010", kind="stock", name="Acme Ltd"))
        s.add(
            StockPriceLatest(
                master_id=MASTER_ID, price=Decimal("80"), prev_close=Decimal("78"),
                price_time=datetime(2026, 2, 3, 15, 30, tzinfo=timezone.utc), source="bhavcopy",
            )
        )  # fmt: skip
        s.commit()
    return client


def add_stock(c, auth_engine, headers, days, priced_stock=True, **overrides):
    name = f"Acme {next(NAMES)}"  # distinct names, so no duplicate warning
    stock_id = add(c, headers, "stock", {**STOCK, "name": name, "buy_date": ago(days), **overrides})
    if priced_stock:
        with sessionmaker(bind=auth_engine)() as s:
            s.get(Stock, stock_id).master_id = MASTER_ID
            s.commit()
    return stock_id


def grid(c, headers, slug, query=""):
    r = c.get(f"/api/holdings/{slug}?{query}", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()["items"]


def compound(row, days):
    """Annual % of a holding with one outflow (invested) and one inflow (current value) today."""
    ratio = float(row["current_value"]) / float(row["invested"])
    return (ratio ** (365 / days) - 1) * 100


def bodies(days):
    return {
        "fd": {**FD, "start_date": ago(days), "tenure_years": 3},
        "rd": {**RD, "start_date": ago(days), "tenure_years": 3},
        "bond": {**BOND, "purchase_date": ago(days)},
        "other": {**OTHER, "acquired_on": ago(days), "value_date": ago(0)},
    }


def seed_all(c, auth_engine, headers, days=400):
    ids = {slug: add(c, headers, slug, body) for slug, body in bodies(days).items()}
    ids["stock"] = add_stock(c, auth_engine, headers, days)
    return ids


def returns_by_holding(c, headers, sale_exits=None):
    """return_pct per (type, id) as the returns endpoint's maths gives it (best and worst rows)."""
    groups = c.get("/api/portfolio", headers=headers).json()["groups"]
    out = analytics_returns.returns(groups, date.today(), sale_exits=sale_exits)
    return {(r["type"], r["id"]): r["return_pct"] for r in (*out["best"], *out["worst"])}


# --- each type ---------------------------------------------------------------------------------


@pytest.mark.parametrize("slug", ["stock", "bond", "other"])
def test_single_outflow_types_report_the_compound_annual_rate(priced, auth_engine, users, slug):
    a = users[0]
    ids = seed_all(priced, auth_engine, a)
    row = next(i for i in grid(priced, a, slug) if i["id"] == ids[slug])
    assert float(row["xirr"]) == pytest.approx(compound(row, 400), abs=0.01)
    assert float(item(priced, a, slug, ids[slug])["xirr"]) == float(row["xirr"])


def test_cumulative_fd_reports_the_compound_annual_rate(priced, users):
    a = users[0]
    fd_id = add(priced, a, "fd", bodies(400)["fd"])
    row = grid(priced, a, "fd")[0]
    assert row["id"] == fd_id and row["status"] == "active"
    assert float(row["xirr"]) == pytest.approx(compound(row, 400), abs=0.01)
    assert float(item(priced, a, "fd", fd_id)["xirr"]) == float(row["xirr"])


def test_rd_and_payout_fd_match_the_returns_maths(priced, users):
    a = users[0]
    rd_id = add(priced, a, "rd", bodies(400)["rd"])
    payout_id = add(priced, a, "fd", {**bodies(400)["fd"], "payout_type": "payout"})
    expected = returns_by_holding(priced, a)
    for slug, hid in (("rd", rd_id), ("fd", payout_id)):
        row = next(i for i in grid(priced, a, slug) if i["id"] == hid)
        assert row["xirr"] is not None
        assert float(row["xirr"]) == float(expected[(slug, hid)])


def test_every_type_agrees_with_the_returns_endpoint(priced, auth_engine, users):
    a = users[0]
    ids = seed_all(priced, auth_engine, a)
    payout_id = add(
        priced, a, "fd", {**bodies(400)["fd"], "payout_type": "payout", "bank": "Payout Bank"}
    )
    expected = returns_by_holding(priced, a)
    pairs = [*ids.items(), ("fd", payout_id)]
    for slug, hid in pairs:
        row = next(i for i in grid(priced, a, slug) if i["id"] == hid)
        assert float(row["xirr"]) == float(expected[(slug, hid)]), slug


def test_other_without_acquired_on_or_invested_and_unpriced_stock_have_none(
    priced, auth_engine, users
):
    a = users[0]
    no_date = add(priced, a, "other", {**bodies(400)["other"], "acquired_on": None})
    no_invested = add(
        priced, a, "other",
        {**bodies(400)["other"], "name": "Plot 2", "invested_amount": None, "acquired_on": None},
    )  # fmt: skip
    at_cost = add_stock(priced, auth_engine, a, 400, priced_stock=False)
    assert {i["id"]: i["xirr"] for i in grid(priced, a, "other")} == {no_date: None, no_invested: None}
    assert grid(priced, a, "stock")[0]["id"] == at_cost
    assert grid(priced, a, "stock")[0]["xirr"] is None


# --- the 365-day rule --------------------------------------------------------------------------


def test_under_a_year_is_none_and_exactly_a_year_is_computed(priced, auth_engine, users):
    a = users[0]
    young = add_stock(priced, auth_engine, a, 364)
    exact = add_stock(priced, auth_engine, a, 365)
    rows = {i["id"]: i for i in grid(priced, a, "stock")}
    assert rows[young]["xirr"] is None
    assert rows[exact]["xirr"] is not None
    assert item(priced, a, "stock", young)["xirr"] is None
    assert float(item(priced, a, "stock", exact)["xirr"]) == pytest.approx(
        compound(rows[exact], 365), abs=0.01
    )


# --- closed holdings ---------------------------------------------------------------------------


def test_matured_fd_and_sold_stock_have_none(priced, auth_engine, users):
    a = users[0]
    matured = add(priced, a, "fd", {**FD, "start_date": ago(800), "tenure_years": 1})
    sold = add_stock(priced, auth_engine, a, 400)
    assert sell(priced, a, "stock", sold, quantity=100, price=90, date=ago(10)).status_code == 201
    fd_row = grid(priced, a, "fd")[0]
    assert fd_row["id"] == matured and fd_row["status"] == "matured" and fd_row["xirr"] is None
    assert item(priced, a, "fd", matured)["xirr"] is None
    sold_row = grid(priced, a, "stock", "status=sold")[0]
    assert sold_row["status"] == "sold" and sold_row["xirr"] is None
    assert item(priced, a, "stock", sold)["xirr"] is None


# --- partly sold -------------------------------------------------------------------------------


def test_partly_sold_stock_uses_its_sale_exits(priced, auth_engine, users):
    a = users[0]
    stock_id = add_stock(priced, auth_engine, a, 400)
    assert sell(priced, a, "stock", stock_id, quantity=40, price=100, date=ago(100)).status_code == 201
    row = grid(priced, a, "stock")[0]
    assert row["status"] == "active" and row["quantity"] == 60
    flows = [
        (date.today() - timedelta(days=400), Decimal("-5000")),
        (date.today() - timedelta(days=100), Decimal("4000")),
        (date.today(), Decimal("4800")),
    ]
    expected = round(float(valuation.xirr(flows)) * 100, 2)
    assert float(row["xirr"]) == pytest.approx(expected, abs=0.01)
    assert float(item(priced, a, "stock", stock_id)["xirr"]) == float(row["xirr"])
    with sessionmaker(bind=auth_engine)() as s:
        exits = list(s.scalars(select(HoldingExit)))
    sale_exits = {("stock", e.holding_id): [e] for e in exits}
    assert float(row["xirr"]) == float(returns_by_holding(priced, a, sale_exits)[("stock", stock_id)])


# --- MF and gold keep their own rule -----------------------------------------------------------


def test_gold_xirr_still_has_no_year_floor(priced, users):
    a = users[0]
    gold_id = add(priced, a, "gold", {**GOLD, "purchase_date": ago(30)})
    assert "xirr" in item(priced, a, "gold", gold_id)
    assert holdings_router.XIRR_TYPES == ("fd", "rd", "stock", "bond", "other")


# --- sorting -----------------------------------------------------------------------------------


def test_sort_by_xirr_puts_none_last_in_both_directions(priced, auth_engine, users):
    a = users[0]
    low = add_stock(priced, auth_engine, a, 400, avg_buy_price=70)
    high = add_stock(priced, auth_engine, a, 400, avg_buy_price=40)
    young = add_stock(priced, auth_engine, a, 30, avg_buy_price=10)
    unpriced = add_stock(priced, auth_engine, a, 400, priced_stock=False)
    asc = [i["id"] for i in grid(priced, a, "stock", "sort=xirr&dir=asc")]
    desc = [i["id"] for i in grid(priced, a, "stock", "sort=xirr&dir=desc")]
    assert asc[:2] == [low, high] and set(asc[2:]) == {young, unpriced}
    assert desc[:2] == [high, low] and set(desc[2:]) == {young, unpriced}


@pytest.mark.parametrize("slug", ["fd", "rd", "bond", "other"])
def test_xirr_is_a_valid_sort_for_every_new_type(priced, users, slug):
    a = users[0]
    add(priced, a, slug, bodies(400)[slug])
    assert len(grid(priced, a, slug, "sort=xirr&dir=desc")) == 1


# --- queries -----------------------------------------------------------------------------------


def count_selects(c, auth_engine, headers, path):
    seen = []

    def record(conn, cursor, statement, *rest):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    event.listen(auth_engine, "before_cursor_execute", record)
    try:
        assert c.get(path, headers=headers).status_code == 200
    finally:
        event.remove(auth_engine, "before_cursor_execute", record)
    return len(seen)


@pytest.mark.parametrize("slug,extra", [("stock", 1), ("bond", 1), ("other", 1), ("fd", 0), ("rd", 0)])
def test_the_grid_costs_at_most_one_extra_query(
    priced, auth_engine, users, monkeypatch, slug, extra
):
    a = users[0]
    seed_all(priced, auth_engine, a)
    sell(priced, a, "bond", grid(priced, a, "bond")[0]["id"], quantity=2, price=1000, date=ago(5))
    path = f"/api/holdings/{slug}"
    with_xirr = count_selects(priced, auth_engine, a, path)
    monkeypatch.setattr(holdings_router, "add_holding_xirr", lambda db, s, uid, items: items)
    without = count_selects(priced, auth_engine, a, path)
    assert with_xirr - without == extra
