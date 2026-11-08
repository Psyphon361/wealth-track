"""GET /api/analytics/capital-gains: sales by financial year, SGB and bond settlements,
soft-deleted holdings and user scoping (SQLite)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.models import Bond, HoldingExit, MFMaster, MFTransaction, StockMaster
from tests.test_exits_api import BOND, STOCK, add
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND

PATH = "/api/analytics/capital-gains"
D = Decimal


@pytest.fixture
def gc(client, auth_engine):  # noqa: F811
    for table in (StockMaster, MFMaster):
        table.__table__.create(auth_engine, checkfirst=True)
    with auth_engine.begin() as conn:
        conn.execute(text("CREATE TABLE bond_master (id INTEGER PRIMARY KEY, bond_type VARCHAR)"))
        conn.execute(text("INSERT INTO bond_master (id, bond_type) VALUES (1, 'sgb'), (2, 'corporate')"))
    with sessionmaker(bind=auth_engine)() as session:
        session.add(StockMaster(id=1, isin="INE000A00011", kind="stock", name="Acme Ltd"))
        session.add(MFMaster(scheme_code=100, name="Fund A - Direct Growth", category="equity", is_active=True))
        session.commit()
    client.factory = sessionmaker(bind=auth_engine)
    return client


def put_exit(c, user_id, asset_type, holding_id, when, amount, cost, kind="sale", **extra):
    with c.factory() as session:
        row = HoldingExit(
            user_id=user_id, asset_type=asset_type, holding_id=holding_id, kind=kind,
            exit_date=when, amount=amount, cost=cost, destination="none", **extra,
        )  # fmt: skip
        session.add(row)
        session.commit()
        return row.id


def get(c, headers, fy=None):
    return c.get(PATH if fy is None else f"{PATH}?fy={fy}", headers=headers)


KEYS = {
    "fy", "fy_start", "fy_end", "as_of", "is_current", "available_fys", "summary", "buckets",
    "sales", "tax_free", "excluded",
}  # fmt: skip


def test_key_set_and_empty_current_year(gc, users):
    a = users[0]
    r = get(gc, a)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert set(body) == KEYS
    assert set(body["summary"]) == {
        "short_term_net", "long_term_net", "losses_set_off", "unused_losses", "exemption_used",
        "fixed_rate_tax", "slab_gains", "sales_count",
    }  # fmt: skip
    assert body["is_current"] is True and body["sales"] == [] and body["buckets"] == []
    assert body["tax_free"] == {"total": 0, "items": []}
    assert body["excluded"] == {"bond_settlements": 0, "no_purchase_date": 0, "old_rules": 0}
    assert [f["is_current"] for f in body["available_fys"]] == [True]


def test_stock_sales_short_and_long_selected_by_fy(gc, users):
    a, a_id, _, _ = users
    short_id = add(gc, a, "stock", {**STOCK, "name": "Short Ltd", "buy_date": "2025-01-01"})
    long_id = add(gc, a, "stock", {**STOCK, "name": "Long Ltd", "buy_date": "2023-01-01"})
    with gc.factory() as s:  # link both to the stock master (kind stock)
        from app.models import Stock

        for row in s.scalars(select(Stock)):
            row.master_id = 1
        s.commit()
    put_exit(gc, a_id, "stock", short_id, date(2025, 8, 1), D("1200.50"), D("1000"), quantity=10)
    put_exit(gc, a_id, "stock", long_id, date(2025, 9, 1), D("3000"), D("2000"), quantity=10)
    old_id = put_exit(gc, a_id, "stock", long_id, date(2024, 5, 1), D("500"), D("400"), quantity=5)

    body = get(gc, a, 2025).json()
    assert body["fy"] == "2025-26" and body["fy_start"] == "2025-04-01" and body["fy_end"] == "2026-03-31"
    assert body["is_current"] is False
    assert [f["start_year"] for f in body["available_fys"]] == [2026, 2025, 2024]
    assert [s["name"] for s in body["sales"]] == ["Long Ltd", "Short Ltd"]  # newest first
    long_sale, short_sale = body["sales"]
    assert long_sale["lots"][0]["term"] == "long" and long_sale["lots"][0]["bucket"] == "equity_lt"
    assert short_sale["lots"][0]["term"] == "short" and short_sale["gain"] == 200.5
    assert short_sale["flags"] == []
    by_key = {b["key"]: b for b in body["buckets"]}
    assert by_key["equity_st"]["net"] == 200.5 and by_key["equity_st"]["tax"] == 40.1
    assert by_key["equity_lt"]["taxable"] == 0  # inside the exemption
    assert body["summary"]["sales_count"] == 2

    older = get(gc, a, 2024).json()
    assert [s["exit_id"] for s in older["sales"]] == [old_id]
    assert get(gc, a).json()["sales"] == []  # current year (2026-27) is empty


def test_partial_mf_sale_splits_by_fifo(gc, users):
    a, a_id, _, _ = users
    fund_id = add(gc, a, "mf", FUND)
    with gc.factory() as s:
        s.add(MFTransaction(mutual_fund_id=fund_id, txn_date=date(2023, 1, 10), kind="purchase", units=D(60), amount=D(2000)))
        s.add(MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 6, 1), kind="purchase", units=D(40), amount=D(2000)))
        red = MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 12, 1), kind="redemption", units=D(80), amount=D(4800))
        s.add(red)
        s.commit()
        red_id = red.id
    exit_id = put_exit(
        gc, a_id, "mf", fund_id, date(2025, 12, 1), D("4800"), D("3000"), quantity=80,
        mf_transaction_id=red_id,
    )  # fmt: skip
    sale = get(gc, a, 2025).json()["sales"][0]
    assert sale["exit_id"] == exit_id and sale["asset_type"] == "mf" and sale["gain"] == 1800
    first, second = sale["lots"]
    assert (first["bought_on"], first["quantity"], first["term"]) == ("2023-01-10", 60, "long")
    assert (second["bought_on"], second["quantity"], second["term"]) == ("2025-06-01", 20, "short")
    assert first["cost"] + second["cost"] == 3000
    assert round(first["gain"] + second["gain"], 2) == 1800


def test_sgb_settlement_is_tax_free_and_other_bond_is_excluded(gc, users):
    a, a_id, _, _ = users
    sgb = add(gc, a, "bond", {**BOND, "name": "SGB 2032"})
    corp = add(gc, a, "bond", {**BOND, "name": "Corp 2035"})
    with gc.factory() as s:
        for bond in s.scalars(select(Bond)):
            bond.master_id = 1 if bond.id == sgb else 2
        s.commit()
    put_exit(gc, a_id, "bond", sgb, date(2025, 10, 1), D("12000"), D("10000"), kind="maturity")
    put_exit(gc, a_id, "bond", corp, date(2025, 11, 1), D("11000"), D("10000"), kind="maturity")
    body = get(gc, a, 2025).json()
    assert body["sales"] == []
    assert body["tax_free"]["total"] == 12000
    [item] = body["tax_free"]["items"]
    assert (item["name"], item["amount"], item["cost"], item["gain"]) == ("SGB 2032", 12000, 10000, 2000)
    assert body["excluded"]["bond_settlements"] == 1
    assert get(gc, a).json()["tax_free"]["items"] == []  # current year (2026-27)


def test_excluded_counts_sales_not_lots(gc, users):
    a, a_id, _, _ = users
    gold_id = add(
        gc, a, "gold",
        {"name": "Coins", "form": "coin", "metal": "gold", "purity": "999", "weight_grams": 10,
         "purchase_date": "2020-01-01", "invested_amount": 50000},
    )  # fmt: skip
    put_exit(gc, a_id, "gold", gold_id, date(2024, 6, 1), D("60000"), D("50000"), quantity=10)
    other = {
        "name": "Plot", "category": "Property", "current_value": 80000,
        "value_date": "2026-01-01", "invested_amount": 50000,
    }  # fmt: skip
    other_id = add(gc, a, "other", other)  # no acquired_on
    put_exit(gc, a_id, "other", other_id, date(2024, 7, 1), D("70000"), D("50000"))
    body = get(gc, a, 2024).json()
    assert body["summary"]["sales_count"] == 2
    assert body["excluded"]["old_rules"] == 1 and body["excluded"]["no_purchase_date"] == 1


def test_soft_deleted_holding_is_skipped(gc, users):
    a, a_id, _, _ = users
    stock_id = add(gc, a, "stock", STOCK)
    put_exit(gc, a_id, "stock", stock_id, date(2025, 8, 1), D("1200"), D("1000"), quantity=10)
    assert len(get(gc, a, 2025).json()["sales"]) == 1
    assert gc.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code in (200, 204)
    assert get(gc, a, 2025).status_code == 422  # year no longer listed once nothing is left
    assert get(gc, a).json()["sales"] == []


def test_other_users_exits_are_not_visible(gc, users):
    a, a_id, b, _ = users
    stock_id = add(gc, a, "stock", STOCK)
    put_exit(gc, a_id, "stock", stock_id, date(2025, 8, 1), D("1200"), D("1000"), quantity=10)
    assert get(gc, b, 2025).status_code == 422
    assert get(gc, b).json()["sales"] == []
    assert len(get(gc, a, 2025).json()["sales"]) == 1


def test_bad_fy_is_422_and_needs_auth(gc, users):
    a = users[0]
    r = get(gc, a, 1999)
    assert r.status_code == 422
    assert r.json()["detail"] == {
        "message": "Invalid financial year",
        "description": "Choose a financial year from the list.",
    }
    assert gc.get(PATH).status_code == 401
