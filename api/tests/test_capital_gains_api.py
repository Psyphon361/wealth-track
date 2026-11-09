"""GET /api/analytics/capital-gains: sales by financial year, SGB and bond settlements,
soft-deleted holdings and user scoping (SQLite)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.models import Bond, HoldingExit, MFMaster, MFTransaction, StockMaster
from app.routers import analytics_gains
from tests.test_exits_api import BOND, STOCK, add
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND

PATH = "/api/analytics/capital-gains"
D = Decimal


class _FixedDate(date):
    @classmethod
    def today(cls):
        return date(2026, 11, 8)


@pytest.fixture
def gc(client, auth_engine, monkeypatch):  # noqa: F811
    monkeypatch.setattr(analytics_gains, "date", _FixedDate)
    for table in (StockMaster, MFMaster):
        table.__table__.create(auth_engine, checkfirst=True)
    with auth_engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE bond_master (id INTEGER PRIMARY KEY, bond_type VARCHAR, issuer VARCHAR,"
                " face_value NUMERIC, coupon_rate NUMERIC, coupon_type VARCHAR,"
                " interest_frequency VARCHAR, issue_date DATE, issue_price NUMERIC,"
                " maturity_date DATE)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO bond_master (id, bond_type, issuer, face_value, issue_price,"
                " maturity_date) VALUES (1, 'sgb', 'RBI', NULL, 6000, NULL),"
                " (2, 'corporate', 'Corp', 1000, NULL, '2035-01-01'),"
                " (4, 'corporate', 'Corp Open', 1000, NULL, NULL),"
                " (5, 'sgb', 'RBI 2032', NULL, 6000, '2032-01-01')"
            )
        )
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
    "sales", "expected", "expected_gain", "tax_free", "bond_interest", "excluded",
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
    assert body["excluded"] == {"bonds_no_face": 0, "no_purchase_date": 0, "old_rules": 0}
    assert body["expected"] == [] and body["expected_gain"] == 0 and body["bond_interest"] is None
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


def test_edited_fund_partial_sale_keeps_real_lot_dates(gc, users):
    a, a_id, _, _ = users
    fund_id = add(gc, a, "mf", FUND)
    with gc.factory() as s:
        s.add(MFTransaction(mutual_fund_id=fund_id, txn_date=date(2023, 1, 10), kind="purchase", units=D(60), amount=D(2000)))
        s.add(MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 6, 1), kind="purchase", units=D(40), amount=D(2000)))
        red = MFTransaction(mutual_fund_id=fund_id, txn_date=date(2025, 12, 1), kind="redemption", units=D(80), amount=D(4800))
        s.add(red)
        s.commit()
        red_id = red.id
    body = {**FUND, "invested_amount": 6000, "avg_nav": 60}
    r = gc.put(f"/api/assets/mf/{fund_id}", json=body, headers=a)
    assert r.status_code == 200, r.json()
    put_exit(
        gc, a_id, "mf", fund_id, date(2025, 12, 1), D("4800"), D("4800"), quantity=80,
        mf_transaction_id=red_id,
    )  # fmt: skip  (pro rata of the edited 6,000: 80/100)
    sale = get(gc, a, 2025).json()["sales"][0]
    first, second = sale["lots"]
    assert (first["bought_on"], first["quantity"], first["term"]) == ("2023-01-10", 60, "long")
    assert (second["bought_on"], second["quantity"], second["term"]) == ("2025-06-01", 20, "short")
    # FIFO costs 2,000 and 1,000 are scaled to the exit cost of 4,800
    assert (first["cost"], second["cost"]) == (3200, 1600)
    assert sale["gain"] == 0


def bond(c, headers, name, master_id=2, **fields):
    """A bond (10 x 1,000 face, 10,000 invested, bought 2025-01-01) linked to a bond_master row."""
    body = {**BOND, "name": name, **fields}
    body["purchase_price"] = body["invested_amount"] / body["quantity"]
    body = {k: v for k, v in body.items() if v is not None}
    bond_id = add(c, headers, "bond", body)
    with c.factory() as s:
        row = s.get(Bond, bond_id)
        row.master_id = master_id
        s.commit()
    return bond_id


def by_name(body, key="sales"):
    return {s["name"]: s for s in body[key]}


def test_unsettled_matured_bonds_count_at_face_value_times_quantity(gc, users):
    a = users[0]
    bond(gc, a, "Premium", master_id=4, invested_amount=10500, maturity_date="2026-06-01")
    bond(gc, a, "Discount", master_id=4, invested_amount=9000, maturity_date="2026-07-01")
    bond(gc, a, "At Par", master_id=4, invested_amount=10000, maturity_date="2026-08-01")
    body = get(gc, a).json()
    sales = by_name(body)
    assert (sales["Premium"]["proceeds"], sales["Premium"]["cost"], sales["Premium"]["gain"]) == (10000, 10500, -500)
    assert sales["Discount"]["gain"] == 1000 and sales["At Par"]["gain"] == 0
    for sale in sales.values():
        assert sale["source"] == "maturity" and sale["estimated"] is True and sale["exit_id"] is None
        assert sale["asset_type"] == "bond" and "estimated" in sale["flags"]
        [lot] = sale["lots"]
        assert lot["bought_on"] == "2025-01-01" and lot["term"] == "long" and lot["bucket"] == "other_lt"
    assert body["summary"]["sales_count"] == 3
    [bucket] = body["buckets"]
    assert (bucket["gains"], bucket["losses"], bucket["net"]) == (1000, 500, 500)
    assert bucket["tax"] == 62.5  # 500 at 12.5%
    assert body["expected"] == [] and body["expected_gain"] == 0
    assert body["excluded"]["bonds_no_face"] == 0
    assert [s["sold_on"] for s in body["sales"]] == ["2026-08-01", "2026-07-01", "2026-06-01"]


def test_settled_bond_counts_once_with_face_value_proceeds(gc, users):
    a, a_id, _, _ = users
    settled = bond(gc, a, "Settled", master_id=4, invested_amount=9000, maturity_date="2026-06-01")
    bond(gc, a, "Unsettled", master_id=4, invested_amount=9000, maturity_date="2026-06-01")
    # The settled amount includes the last coupon; it must not drive the gain.
    put_exit(gc, a_id, "bond", settled, date(2026, 6, 1), D("10800"), D("9000"), kind="maturity")
    body = get(gc, a).json()
    assert len(body["sales"]) == 2
    sales = by_name(body)
    assert sales["Settled"]["source"] == "maturity"
    assert sales["Settled"]["proceeds"] == 10000 and sales["Settled"]["gain"] == 1000
    assert sales["Settled"] == {**sales["Unsettled"], "name": "Settled", "holding_id": settled}
    assert body["tax_free"]["items"] == []


def test_planned_sale_bond_past_date_is_counted_and_future_date_is_expected(gc, users):
    a = users[0]
    # The master matures in 2035; the holding's date is an earlier planned exit.
    bond(gc, a, "Planned Past", invested_amount=9500, maturity_date="2026-09-01")
    bond(gc, a, "Planned Later", invested_amount=9000, maturity_date="2027-01-15")
    body = get(gc, a).json()
    [past] = body["sales"]
    assert past["name"] == "Planned Past" and past["source"] == "planned_sale"
    assert past["estimated"] is True and past["proceeds"] == 10000 and past["gain"] == 500
    [later] = body["expected"]
    assert later["name"] == "Planned Later" and later["source"] == "planned_sale"
    assert later["gain"] == 1000 and later["sold_on"] == "2027-01-15"
    assert body["expected_gain"] == 1000
    assert body["summary"]["sales_count"] == 1
    [bucket] = body["buckets"]
    assert bucket["net"] == 500  # the expected sale stays out of the totals


def test_partial_and_full_sales_and_deleted_bonds(gc, users):
    a, _, _, _ = users
    bond(gc, a, "Partly Sold", quantity=4, invested_amount=3800, maturity_date="2026-06-01")
    sold = bond(gc, a, "Fully Sold", maturity_date="2026-06-01")
    gone = bond(gc, a, "Deleted", maturity_date="2026-06-01")
    with gc.factory() as s:
        s.get(Bond, sold).closed_on = date(2026, 5, 1)
        s.commit()
    assert gc.delete(f"/api/assets/bond/{gone}", headers=a).status_code in (200, 204)
    body = get(gc, a).json()
    [only] = body["sales"]
    assert only["name"] == "Partly Sold"
    assert (only["proceeds"], only["cost"], only["gain"]) == (4000, 3800, 200)
    assert only["lots"][0]["quantity"] == 4


def test_sgb_maturity_is_tax_free_estimated_or_settled(gc, users):
    a, a_id, _, _ = users
    bond(gc, a, "SGB Estimated", master_id=1, quantity=5, invested_amount=25000, maturity_date="2026-05-01")
    settled = bond(gc, a, "SGB Settled", master_id=1, quantity=5, invested_amount=25000, maturity_date="2026-05-02")
    bond(gc, a, "SGB Later", master_id=1, quantity=5, invested_amount=25000, maturity_date="2027-02-01")
    put_exit(gc, a_id, "bond", settled, date(2026, 5, 10), D("31000"), D("25000"), kind="maturity")
    body = get(gc, a).json()
    assert body["sales"] == [] and body["expected"] == []
    items = {i["name"]: i for i in body["tax_free"]["items"]}
    assert set(items) == {"SGB Estimated", "SGB Settled"}  # the later one is not due yet
    est, done = items["SGB Estimated"], items["SGB Settled"]
    assert (est["amount"], est["cost"], est["gain"]) == (30000, 25000, 5000)  # 6,000 x 5 grams
    assert est["estimated"] is True and est["exit_id"] is None and est["settled_on"] == "2026-05-01"
    assert (done["amount"], done["gain"], done["estimated"]) == (31000, 6000, False)
    assert done["exit_id"] is not None and done["settled_on"] == "2026-05-10"
    assert body["tax_free"]["total"] == 61000
    assert body["excluded"]["bonds_no_face"] == 0


def test_planned_sale_sgb_is_a_taxable_sale(gc, users):
    a = users[0]
    bond(gc, a, "SGB Early", master_id=5, quantity=5, invested_amount=25000, maturity_date="2026-09-01")
    body = get(gc, a).json()
    assert body["tax_free"]["items"] == []
    [sale] = body["sales"]
    assert sale["source"] == "planned_sale" and sale["estimated"] is True
    assert (sale["proceeds"], sale["gain"]) == (30000, 5000)


def test_bond_without_face_value_is_counted_not_computed(gc, users):
    a = users[0]
    bond(gc, a, "No Face", master_id=None, face_value=None, maturity_date="2026-06-01")
    body = get(gc, a).json()
    assert body["sales"] == [] and body["excluded"]["bonds_no_face"] == 1


def test_bond_interest_for_current_year_only(gc, users):
    a = users[0]
    with gc.factory() as s:
        s.execute(
            text(
                "INSERT INTO bond_master (id, bond_type, issuer, face_value, coupon_rate,"
                " interest_frequency, maturity_date) VALUES (3, 'corporate', 'Coupon Co', 1000,"
                " 8, 'yearly', '2035-03-01')"
            )
        )
        s.commit()
    bond(gc, a, "Coupon Bond", master_id=3, maturity_date="2035-03-01")
    bond(gc, a, "Old Bond", master_id=2, purchase_date="2023-01-01", maturity_date="2024-09-01")
    current = get(gc, a).json()
    assert current["bond_interest"] == {
        "interest_to_date": 0, "interest_projected": 800, "tds_estimate": 80, "holdings_count": 1,
    }  # fmt: skip
    older = get(gc, a, 2024).json()
    assert older["bond_interest"] is None
    assert [s["name"] for s in older["sales"]] == ["Old Bond"]
    assert [f["start_year"] for f in older["available_fys"]] == [2026, 2024]


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
    # The API refuses to delete a sold holding now; this is a legacy row deleted before that rule.
    with gc.factory() as session:
        session.execute(text("UPDATE stocks SET deleted_at = CURRENT_TIMESTAMP WHERE id = :i"), {"i": stock_id})
        session.commit()
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
