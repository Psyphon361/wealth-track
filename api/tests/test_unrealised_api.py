"""GET /api/analytics/unrealised: real rows in SQLite, `today` fixed to 2026-11-08 (the date the
capital-gains router is patched to). Expected figures are hand-worked literals.

User A's open holdings:
  Eq Stock     10 x 100 bought 2025-01-01, price 150  -> 1,000 / 1,500, long, equity_lt, gain 500
  No Price     stock with no price                     -> at cost, excluded
  Fund A       equity fund, NAV 48; purchases 80 u 2025-01-10 (3,200) and 60 u 2026-06-01 (3,000),
               a redemption of 40 u on 2026-07-01 -> lots left 40 u (cost 1,600, value 1,920, gain
               320, long) and 60 u (cost 3,000, value 2,880, gain -120, short)
  Coins        10 g gold 999 bought 2025-01-01 for 50,000, rate 6,000 -> 60,000, short, slab,
               long term (other, 24 months) on 2027-01-02
  Coin Hodl    Other "Crypto" 50,000 -> 40,000 (flat, loss, not a loss lot)
  Plot         Other "Property" with no invested amount -> no_invested_amount, excluded
  No Face      bond with no master and no face value    -> excluded
  Sold Stock   closed, with a recorded sale of 30,000 gain on 2026-08-01 (long, equity_lt)
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models import (
    GoldRateLatest,
    MFNavHistory,
    MFNavHistorySync,
    MFNavLatest,
    MFTransaction,
    Stock,
    StockPriceLatest,
)
from tests.test_capital_gains_api import (  # noqa: F401  (fixtures and helpers)
    PATH,
    bond,
    gc,
    get,
    put_exit,
)
from tests.test_exits_api import GOLD, OTHER, STOCK, add
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND

D = Decimal
UPATH = "/api/analytics/unrealised"
FUND_NAME = "Fund A - Direct Growth"  # the name the AMFI master gives scheme 100


@pytest.fixture
def ur(gc, auth_engine):  # noqa: F811
    for table in (StockPriceLatest, MFNavHistory, MFNavHistorySync):
        table.__table__.create(auth_engine, checkfirst=True)
    with gc.factory() as s:
        s.add(
            StockPriceLatest(
                master_id=1, price=150, prev_close=149,
                price_time=datetime(2026, 11, 6, tzinfo=timezone.utc), source="bhavcopy",
            )
        )  # fmt: skip
        s.add(MFNavLatest(scheme_code=100, nav=48, nav_date=date(2026, 11, 6)))
        s.add(GoldRateLatest(metal="gold", purity="999", rate_per_gram=6000, rate_date=date(2026, 11, 6), session="PM", source="ibja"))
        s.commit()
    return gc


def uget(c, headers, fy=None):
    return c.get(UPATH if fy is None else f"{UPATH}?fy={fy}", headers=headers)


def link_stock(c, stock_id, **fields):
    with c.factory() as s:
        row = s.get(Stock, stock_id)
        row.master_id = 1
        for k, v in fields.items():
            setattr(row, k, v)
        s.commit()


def seed(c, a, a_id):
    eq = add(c, a, "stock", {**STOCK, "name": "Eq Stock", "quantity": 10, "avg_buy_price": 100})
    link_stock(c, eq)
    add(c, a, "stock", {**STOCK, "name": "No Price"})
    sold = add(c, a, "stock", {**STOCK, "name": "Sold Stock", "buy_date": "2024-01-01"})
    link_stock(c, sold, closed_on=date(2026, 8, 1))
    put_exit(c, a_id, "stock", sold, date(2026, 8, 1), D("31000"), D("1000"), quantity=10)
    fund = add(c, a, "mf", {**FUND, "units": 100, "avg_nav": 46, "invested_amount": 4600})
    with c.factory() as s:
        s.add(MFTransaction(mutual_fund_id=fund, txn_date=date(2025, 1, 10), kind="purchase", units=D(80), amount=D(3200)))
        s.add(MFTransaction(mutual_fund_id=fund, txn_date=date(2026, 6, 1), kind="purchase", units=D(60), amount=D(3000)))
        s.add(MFTransaction(mutual_fund_id=fund, txn_date=date(2026, 7, 1), kind="redemption", units=D(40), amount=D(2000)))
        s.commit()
    add(c, a, "gold", GOLD)
    add(c, a, "other", {**OTHER, "name": "Coin Hodl", "category": "Crypto", "current_value": 40000, "acquired_on": None})
    add(c, a, "other", {**OTHER, "name": "Plot", "invested_amount": None})
    bond(c, a, "No Face", master_id=None, face_value=None)
    return eq


def test_empty_portfolio(ur, users):
    body = uget(ur, users[0]).json()
    assert body["holdings"] == [] and body["buckets"] == []
    assert body["summary"] == {"total_gain": 0, "short_term_net": 0, "long_term_net": 0, "uncounted_lots": 0}
    assert body["harvest"] == {
        "exemption_limit": 125000, "exemption_used": 0, "exemption_room": 125000,
        "unrealised_equity_lt_gain": 0, "turning_long_term": [], "loss_lots": [],
    }  # fmt: skip
    assert body["excluded"] == {"at_cost": 0, "no_invested_amount": 0, "bonds_no_face": 0, "no_purchase_date": 0}
    assert body["fy"] == "2026-27" and body["is_current"] is True and body["as_of"] == "2026-11-08"


def test_mixed_portfolio(ur, users):
    a, a_id, _, _ = users
    seed(ur, a, a_id)
    r = uget(ur, a)
    assert r.status_code == 200, r.json()
    body = r.json()
    by_name = {h["name"]: h for h in body["holdings"]}
    assert set(by_name) == {"Eq Stock", FUND_NAME, "Coins", "Coin Hodl"}
    assert body["excluded"] == {"at_cost": 1, "no_invested_amount": 1, "bonds_no_face": 1, "no_purchase_date": 0}

    stock = by_name["Eq Stock"]
    assert (stock["cost"], stock["value"], stock["gain"]) == (1000, 1500, 500)
    assert stock["flags"] == ["single_lot_average"]
    [lot] = stock["lots"]
    assert (lot["term"], lot["bucket"], lot["long_term_on"], lot["days_to_long_term"]) == ("long", "equity_lt", None, None)

    fund = by_name[FUND_NAME]
    first, second = fund["lots"]
    assert (first["bought_on"], first["quantity"], first["cost"], first["value"], first["gain"]) == ("2025-01-10", 40, 1600, 1920, 320)
    assert (first["term"], first["bucket"]) == ("long", "equity_lt")
    assert (second["bought_on"], second["quantity"], second["cost"], second["value"], second["gain"]) == ("2026-06-01", 60, 3000, 2880, -120)
    assert (second["term"], second["bucket"], second["long_term_on"], second["bucket_after"]) == ("short", "equity_st", "2027-06-02", "equity_lt")

    [coins] = by_name["Coins"]["lots"]
    assert (coins["value"], coins["gain"], coins["term"], coins["bucket"]) == (60000, 10000, "short", "slab")
    assert (coins["long_term_on"], coins["days_to_long_term"], coins["bucket_after"]) == ("2027-01-02", 55, "other_lt")
    [crypto] = by_name["Coin Hodl"]["lots"]
    assert (crypto["gain"], crypto["term"], crypto["bucket"], crypto["long_term_on"]) == (-10000, "flat", "crypto", None)

    keys = {b["key"]: b for b in body["buckets"]}
    assert [b["key"] for b in body["buckets"]] == ["equity_st", "equity_lt", "slab", "crypto"]
    assert (keys["equity_lt"]["gains"], keys["equity_lt"]["net"]) == (820, 820)
    assert (keys["equity_st"]["losses"], keys["equity_st"]["net"]) == (120, -120)
    assert (keys["crypto"]["losses"], keys["slab"]["net"]) == (10000, 10000)
    assert body["summary"] == {
        "total_gain": 820 - 120 + 10000 - 10000, "short_term_net": -120 + 10000 - 10000,
        "long_term_net": 820, "uncounted_lots": 0,
    }  # fmt: skip

    harvest = body["harvest"]
    assert harvest["unrealised_equity_lt_gain"] == 820
    # realised this year: 30,000 equity long-term gain
    assert (harvest["exemption_used"], harvest["exemption_room"]) == (30000, 95000)
    assert [t["name"] for t in harvest["turning_long_term"]] == ["Coins"]
    assert harvest["turning_long_term"][0]["long_term_on"] == "2027-01-02"
    assert [(t["name"], t["gain"]) for t in harvest["loss_lots"]] == [(FUND_NAME, -120)]  # crypto excluded


def test_past_fy_shows_that_years_exemption_usage(ur, users):
    a, a_id, _, _ = users
    seed(ur, a, a_id)
    old = add(ur, a, "stock", {**STOCK, "name": "Old Sale", "buy_date": "2023-01-01"})
    link_stock(ur, old, closed_on=date(2025, 8, 1))
    put_exit(ur, a_id, "stock", old, date(2025, 8, 1), D("11000"), D("1000"), quantity=10)
    body = uget(ur, a, 2025).json()
    assert body["is_current"] is False and body["fy"] == "2025-26"
    assert (body["harvest"]["exemption_used"], body["harvest"]["exemption_room"]) == (10000, 115000)
    assert body["as_of"] == "2026-11-08" and len(body["holdings"]) == 4  # unrealised is always today


def test_other_users_holdings_are_not_visible(ur, users):
    a, a_id, b, _ = users
    seed(ur, a, a_id)
    body = uget(ur, b).json()
    assert body["holdings"] == [] and body["excluded"]["at_cost"] == 0
    assert body["harvest"]["exemption_used"] == 0


def test_bad_fy_is_422_and_needs_auth(ur, users):
    r = uget(ur, users[0], 1999)
    assert r.status_code == 422
    assert r.json()["detail"] == {
        "message": "Invalid financial year",
        "description": "Choose a financial year from the list.",
    }
    assert ur.get(UPATH).status_code == 401
