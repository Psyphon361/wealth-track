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

from fastapi import HTTPException

from app.models import Cash, HoldingFunding, MfSip, MutualFund
from app.models.nps import Nps
from app.routers.exits import MODELS, _get_holding
from app.schemas.fundings import PaidFromBody
from app.services.fundings import plan
from app.services.sip import _post_one, post_due
from tests.test_exits_api import BOND, FD, STOCK, add, asset, sell, settle
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


# Note: the two double-request tests below run sequentially, so they only prove the re-check after
# the lock (the second request finds nothing to do), not the locks; the lock tests cover those.
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


def test_fd_locks_only_the_holding_table(env, db, users, locked_statements):
    """FD joins the issuer master eagerly; FOR UPDATE must name fixed_deposits."""
    a = users[0]
    fd_id = add(env, a, "fd", FD)
    locked_statements.clear()
    with pytest.raises(HTTPException):  # no such user: only the compiled statement matters
        _get_holding(db, "fd", fd_id, SimpleNamespace(id=-1), lock=True)
    fd_sql = [s for s in locked_statements if "FROM fixed_deposits" in s]
    assert fd_sql
    for sql in fd_sql:
        assert "FOR UPDATE OF fixed_deposits" in sql
        assert "FOR UPDATE" not in sql.replace("FOR UPDATE OF fixed_deposits", "")


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


# Note: sequential requests, so these two only prove the state re-check, not the row locks.
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


def test_sip_stopped_elsewhere_is_not_posted_from_a_stale_object(sdb):  # noqa: F811
    add_nav(sdb, CODE, date(2026, 3, 5))
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Groww",
        category="equity", units=Decimal("100"), avg_nav=Decimal("40"),
        invested_amount=Decimal("4000"), purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    for status in ("stopped", "paused"):
        sip = new_sip(
            sdb, mutual_fund_id=holding.id, start_date=date(2026, 3, 5), post_from=date(2026, 3, 5)
        )
        assert sip.status == "active"
        sdb.execute(  # committed elsewhere (a full sale stops the SIP); this object stays stale
            sa.update(MfSip.__table__).where(MfSip.__table__.c.id == sip.id).values(status=status)
        )
        assert sip.status == "active"  # still stale in the identity map

        assert _post_one(sdb, sip, date(2026, 3, 10)) == 0
        sdb.expire_all()
        assert sdb.get(MutualFund, holding.id).units == Decimal("100")
        assert sdb.get(MfSip, sip.id).last_posted_on is None


def test_reinvest_plan_locks_the_exit_before_the_cash_account(env, db, users, locked_statements):
    a = users[0]
    cash_id = source(env, a, balance=60000)
    _stock_id, sale = sell_into(env, a, cash_id)
    cash = db.get(Cash, cash_id)
    locked_statements.clear()
    plan(
        db, cash.user_id, "stock", STOCK, PaidFromBody(cash_id=cash_id, from_exit_id=sale["id"]),
        date(2026, 3, 10),
    )
    order = [
        "holding_exits" if "FROM holding_exits" in sql else "cash_holdings"
        for sql in locked_statements
        if "FROM holding_exits" in sql or "FROM cash_holdings" in sql
    ]
    assert order == ["holding_exits", "cash_holdings"]


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


def test_sip_posting_loads_nav_history_before_any_lock_and_commits_once_after(sdb, monkeypatch):  # noqa: F811
    """A history fetch commits; inside the locked loop that would drop the locks."""
    from datetime import datetime, timezone

    from app.models import MFNavHistory, MFNavHistorySync
    from app.services import sip as sip_service

    log: list[str] = []

    def fake_fetch(session, code):
        log.append("fetch")
        for day in (date(2026, 1, 5), date(2026, 2, 5)):
            session.add(MFNavHistory(scheme_code=code, nav_date=day, nav=Decimal("50")))
        session.add(
            MFNavHistorySync(
                scheme_code=code, first_date=date(2025, 1, 1), last_date=date(2026, 2, 5),
                fetched_at=datetime.now(timezone.utc),
            )
        )  # fmt: skip
        session.commit()  # what store_history does

    def on_execute(state):
        statement = state.statement
        if isinstance(statement, sa.Select) and "FOR UPDATE" in str(
            statement.compile(dialect=postgresql.dialect())
        ):
            log.append("lock")

    def on_commit(_session):
        log.append("commit")

    def on_rollback(_session):
        log.append("rollback")

    monkeypatch.setattr(sip_service, "ensure_history", fake_fetch)
    sip = new_sip(sdb, start_date=date(2026, 1, 5), post_from=date(2026, 1, 5))
    log.clear()
    event.listen(Session, "do_orm_execute", on_execute)
    event.listen(Session, "after_commit", on_commit)
    event.listen(Session, "after_rollback", on_rollback)
    try:
        assert post_due(sdb, date(2026, 2, 10)) == {sip.id: 2}
    finally:
        event.remove(Session, "do_orm_execute", on_execute)
        event.remove(Session, "after_commit", on_commit)
        event.remove(Session, "after_rollback", on_rollback)

    assert log.count("fetch") == 1
    first_lock = log.index("lock")
    assert log.index("fetch") < first_lock
    assert log[first_lock:].count("commit") == 1 and log[-1] == "commit"
    assert "rollback" not in log[first_lock:]


def test_a_sip_paused_after_it_was_loaded_posts_nothing(sdb, monkeypatch):  # noqa: F811
    from app.services import sip as sip_service

    add_nav(sdb, CODE, date(2026, 3, 5))
    sip = new_sip(sdb, start_date=date(2026, 3, 5), post_from=date(2026, 3, 5))
    real = sip_service._prefetch_history

    def pause_meanwhile(session, loaded, today):
        real(session, loaded, today)
        session.execute(  # a pause committed by another request after post_due loaded the SIP
            sa.update(MfSip.__table__).where(MfSip.__table__.c.id == loaded.id).values(status="paused")
        )

    monkeypatch.setattr(sip_service, "_prefetch_history", pause_meanwhile)
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 0}
    sdb.expire_all()
    assert sdb.get(MfSip, sip.id).last_posted_on is None
    assert sdb.scalar(sa.select(sa.func.count()).select_from(MutualFund)) == 0


def test_a_sip_linked_by_another_run_meanwhile_posts_nothing_and_makes_no_second_holding(  # noqa: F811
    sdb, monkeypatch
):
    from app.models import MFTransaction
    from app.services import sip as sip_service

    add_nav(sdb, CODE, date(2026, 3, 5))
    other = MutualFund(
        user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Other",
        category="equity", units=Decimal("10"), avg_nav=Decimal("40"),
        invested_amount=Decimal("400"), purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(other)
    sdb.commit()
    sip = new_sip(sdb, start_date=date(2026, 3, 5), post_from=date(2026, 3, 5))  # no holding linked
    real = sip_service._active_target

    def linked_meanwhile(session, loaded):
        found = real(session, loaded)  # the choice is made while the SIP has no holding
        session.execute(  # ... then another run links the SIP and commits
            sa.update(MfSip.__table__)
            .where(MfSip.__table__.c.id == loaded.id)
            .values(mutual_fund_id=other.id)
        )
        session.commit()
        return found

    monkeypatch.setattr(sip_service, "_active_target", linked_meanwhile)
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 0}
    sdb.expire_all()
    assert sdb.scalar(sa.select(sa.func.count()).select_from(MutualFund)) == 1
    assert sdb.scalar(sa.select(sa.func.count()).select_from(MFTransaction)) == 0
    assert sdb.get(MfSip, sip.id).last_posted_on is None


def test_every_early_exit_after_the_locks_ends_the_transaction(sdb, monkeypatch):  # noqa: F811
    """No fund or SIP row lock may stay open while the next SIP's history is fetched."""
    from app.services import sip as sip_service

    add_nav(sdb, CODE, date(2026, 3, 5))
    cases = {
        "paused": dict(start_date=date(2026, 3, 5), post_from=date(2026, 3, 5)),
        "nothing due": dict(start_date=date(2026, 4, 5), post_from=date(2026, 4, 5)),
    }
    for name, fields in cases.items():
        sip = new_sip(sdb, **fields)
        if name == "paused":
            sdb.execute(
                sa.update(MfSip.__table__).where(MfSip.__table__.c.id == sip.id).values(status="paused")
            )
        log: list[str] = []

        def on_execute(state, log=log):
            statement = state.statement
            if isinstance(statement, sa.Select) and "FOR UPDATE" in str(
                statement.compile(dialect=postgresql.dialect())
            ):
                log.append("lock")

        def on_commit(_s, log=log):
            log.append("commit")

        def on_rollback(_s, log=log):
            log.append("rollback")

        event.listen(Session, "do_orm_execute", on_execute)
        event.listen(Session, "after_commit", on_commit)
        event.listen(Session, "after_rollback", on_rollback)
        try:
            assert sip_service._post_one(sdb, sip, date(2026, 3, 10)) == 0
        finally:
            event.remove(Session, "do_orm_execute", on_execute)
            event.remove(Session, "after_commit", on_commit)
            event.remove(Session, "after_rollback", on_rollback)
        tail = log[log.index("lock"):]
        assert tail[-1] == "rollback", (name, log)
        assert "commit" not in tail, (name, log)
        sdb.execute(sa.delete(MfSip.__table__))
        sdb.commit()


def test_two_matching_holdings_after_a_sale_make_one_fresh_holding(sdb):  # noqa: F811
    from app.models import MFTransaction

    add_nav(sdb, CODE, date(2026, 1, 5))
    add_nav(sdb, CODE, date(2026, 2, 5))

    def fund(**kw):
        fields = dict(
            user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Groww",
            category="equity", units=Decimal("10"), avg_nav=Decimal("40"),
            invested_amount=Decimal("400"), purchase_date=date(2025, 6, 1),
        )  # fmt: skip
        fields.update(kw)
        row = MutualFund(**fields)
        sdb.add(row)
        sdb.commit()
        return row

    sold = fund(closed_on=date(2025, 12, 1))
    fund()
    fund()
    sip = new_sip(sdb, mutual_fund_id=sold.id, start_date=date(2026, 1, 5), post_from=date(2026, 1, 5))
    assert post_due(sdb, date(2026, 2, 10)) == {sip.id: 2}
    sdb.expire_all()
    assert sdb.scalar(sa.select(sa.func.count()).select_from(MutualFund)) == 4
    fresh_id = sdb.get(MfSip, sip.id).mutual_fund_id
    assert fresh_id != sold.id
    fresh = sdb.get(MutualFund, fresh_id)
    assert fresh.closed_on is None and fresh.units > Decimal("100")
    assert sdb.scalar(
        sa.select(sa.func.count())
        .select_from(MFTransaction)
        .where(MFTransaction.mutual_fund_id == fresh_id)
    ) == 2
