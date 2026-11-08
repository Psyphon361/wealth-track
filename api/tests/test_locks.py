"""Race conditions on money-moving endpoints: row locks plus a re-check after the lock.

SQLite ignores FOR UPDATE, so the lock tests compile the statements for Postgres; the other tests
play the second request after the first and assert that no money moves twice.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import HoldingFunding, MutualFund
from app.models.nps import Nps
from app.routers.exits import MODELS, _get_holding
from app.services.sip import post_due
from tests.test_exits_api import BOND, STOCK, add, asset, sell, settle
from tests.test_paid_from import (  # noqa: F401  (fixtures)
    NPS,
    add_paid,
    balance,
    db,
    env,
    sell_into,
    source,
)
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import sc  # noqa: F401  (fixture)
from tests.test_sip import CODE, USER, add_nav, new_sip, sdb  # noqa: F401  (fixtures)


@pytest.fixture
def locked_statements():
    """Postgres SQL of every ORM select that carries FOR UPDATE."""
    seen: list[str] = []

    def listener(state):
        statement = state.statement
        if isinstance(statement, sa.Select):
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FOR UPDATE" in sql:
                seen.append(sql)

    event.listen(Session, "do_orm_execute", listener)
    yield seen
    event.remove(Session, "do_orm_execute", listener)


def locked_tables(statements: list[str]) -> set[str]:
    return {name for sql in statements for name in ("holding_fundings", "holding_exits",
            "stocks", "mutual_funds", "cash_holdings") if f"FROM {name}" in sql}  # fmt: skip


# --- delete and restore ---------------------------------------------------------------------


def test_double_delete_refunds_once(env, users):
    a = users[0]
    cash_id = source(env, a, balance=100000)
    r = add_paid(env, a, "stock", STOCK, cash_id)
    assert r.status_code == 201, r.json()
    stock_id = r.json()["id"]
    assert balance(env, a, cash_id)[0] == 95000

    assert env.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 100000
    second = env.delete(f"/api/assets/stock/{stock_id}", headers=a)
    assert second.status_code == 404
    assert balance(env, a, cash_id)[0] == 100000


def test_double_restore_debits_once(env, db, users):
    a = users[0]
    cash_id = source(env, a, balance=100000)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    assert env.delete(f"/api/assets/stock/{stock_id}", headers=a).status_code == 200

    assert env.post(f"/api/assets/stock/{stock_id}/restore", headers=a).status_code == 200
    assert balance(env, a, cash_id)[0] == 95000
    second = env.post(f"/api/assets/stock/{stock_id}/restore", headers=a)
    assert second.status_code == 404
    assert balance(env, a, cash_id)[0] == 95000
    db.expire_all()
    [funding] = db.scalars(sa.select(HoldingFunding)).all()
    assert funding.refunded_at is None


def test_delete_and_restore_lock_the_holding_and_its_fundings(env, users, locked_statements):
    a = users[0]
    cash_id = source(env, a, balance=100000)
    stock_id = add_paid(env, a, "stock", STOCK, cash_id).json()["id"]
    locked_statements.clear()
    env.delete(f"/api/assets/stock/{stock_id}", headers=a)
    assert {"stocks", "holding_fundings"} <= locked_tables(locked_statements)
    locked_statements.clear()
    env.post(f"/api/assets/stock/{stock_id}/restore", headers=a)
    assert {"stocks", "holding_fundings"} <= locked_tables(locked_statements)


def test_nps_locks_only_the_holding_table(env, db, users, locked_statements, monkeypatch):
    """Nps joins nps_master eagerly; FOR UPDATE must name nps_holdings or Postgres refuses it."""
    monkeypatch.setitem(MODELS, "nps", Nps)  # exits never close an NPS; this checks the statement shape
    a = users[0]
    nps_id = add(env, a, "nps", NPS)
    locked_statements.clear()
    assert env.delete(f"/api/assets/nps/{nps_id}", headers=a).status_code == 200
    delete_sql = list(locked_statements)
    locked_statements.clear()
    assert env.post(f"/api/assets/nps/{nps_id}/restore", headers=a).status_code == 200
    restore_sql = list(locked_statements)
    locked_statements.clear()
    _get_holding(db, "nps", nps_id, SimpleNamespace(id=1), lock=True)
    exits_sql = list(locked_statements)

    for sqls in (delete_sql, restore_sql, exits_sql):
        nps_sql = [s for s in sqls if "FROM nps_holdings" in s]
        assert nps_sql
        for sql in nps_sql:
            assert "FOR UPDATE OF nps_holdings" in sql
            assert "FOR UPDATE" not in sql.replace("FOR UPDATE OF nps_holdings", "")


# --- sell, settle and undo ------------------------------------------------------------------


def test_sell_after_settle_is_refused(client, users):  # noqa: F811
    a = users[0]
    bond = add(client, a, "bond", {**BOND, "purchase_date": "2024-01-01", "maturity_date": "2025-01-01"})
    assert settle(client, a, "bond", bond).status_code == 201
    r = sell(client, a, "bond", bond, quantity=10, price=1000)
    assert r.status_code == 409
    assert r.json()["message"] == "This bond has matured"


def test_settle_after_sell_is_refused(client, users):  # noqa: F811
    a = users[0]
    bond = add(client, a, "bond", BOND)
    assert sell(client, a, "bond", bond, quantity=10, price=1000).status_code == 201
    r = settle(client, a, "bond", bond)
    assert r.status_code == 409
    assert r.json()["message"] == "Already sold"


def test_undo_after_a_reinvest_is_refused(env, users):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    _stock_id, sale = sell_into(env, a, cash_id)
    r = add_paid(env, a, "stock", STOCK, cash_id, from_exit_id=sale["id"])
    assert r.status_code == 201, r.json()
    before = balance(env, a, cash_id)

    undo = env.delete(f"/api/exits/{sale['id']}", headers=a)
    assert undo.status_code == 409
    assert undo.json()["message"] == "Some of this money was reinvested"
    assert balance(env, a, cash_id) == before


def test_settle_sell_undo_and_reinvest_lock_their_rows(env, users, locked_statements):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    bond = add(env, a, "bond", {**BOND, "purchase_date": "2024-01-01", "maturity_date": "2025-01-01"})
    locked_statements.clear()
    assert settle(env, a, "bond", bond).status_code == 201
    assert any("FROM bonds" in sql for sql in locked_statements)

    _stock_id, sale = sell_into(env, a, cash_id)
    locked_statements.clear()
    assert add_paid(env, a, "other", {**STOCK_OTHER}, cash_id, from_exit_id=sale["id"]).status_code == 201
    assert "holding_exits" in locked_tables(locked_statements)

    locked_statements.clear()
    env.delete(f"/api/exits/{sale['id']}", headers=a)  # refused, but the exit row is locked first
    assert "holding_exits" in locked_tables(locked_statements)


STOCK_OTHER = {
    "name": "Plot", "category": "Property", "current_value": 80000, "value_date": "2026-01-01",
    "invested_amount": 50000, "acquired_on": "2024-01-01",
}  # fmt: skip


# --- SIP posting ----------------------------------------------------------------------------


def test_sip_posting_uses_the_units_left_after_a_concurrent_sale(sdb):  # noqa: F811
    add_nav(sdb, CODE, date(2026, 3, 5))
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Groww",
        category="equity", units=Decimal("100"), avg_nav=Decimal("40"),
        invested_amount=Decimal("4000"), purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    sip = new_sip(sdb, mutual_fund_id=holding.id, start_date=date(2026, 3, 5), post_from=date(2026, 3, 5))
    sdb.get(MutualFund, holding.id)  # this session now holds the pre-sale state
    sdb.execute(  # a sale committed elsewhere: 60 of the 100 units gone
        sa.update(MutualFund.__table__)
        .where(MutualFund.__table__.c.id == holding.id)
        .values(units=Decimal("40"), invested_amount=Decimal("1600"))
    )

    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 1}
    sdb.expire_all()
    fresh = sdb.get(MutualFund, holding.id)
    assert fresh.units == Decimal("40") + Decimal("99.995")
    assert fresh.invested_amount == Decimal("6600")


def test_sip_posting_locks_the_fund_row(sdb, locked_statements):  # noqa: F811
    add_nav(sdb, CODE, date(2026, 3, 5))
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Groww",
        category="equity", units=Decimal("100"), avg_nav=Decimal("40"),
        invested_amount=Decimal("4000"), purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    new_sip(sdb, mutual_fund_id=holding.id, start_date=date(2026, 3, 5), post_from=date(2026, 3, 5))
    locked_statements.clear()
    post_due(sdb, date(2026, 3, 10))
    assert "mutual_funds" in locked_tables(locked_statements)
