"""Every real FOR UPDATE path runs on Postgres, plus read_bind and the soft-delete filter.

SQLite ignores FOR UPDATE, so only a real server proves the statements are valid (the earlier bug:
a bare FOR UPDATE on a LEFT OUTER JOIN of Nps or a joined master fails on Postgres). Each test
drives the real HTTP endpoint and asserts the effect, not just "no 500".
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text

from app.db import read_bind
from app.models import (
    Cash,
    FixedDeposit,
    HoldingExit,
    HoldingFunding,
    MFTransaction,
    MfSip,
    MutualFund,
    Nps,
    Stock,
)
from app.services import nps as nps_service
from app.services import sip as sip_service
from tests.pg.conftest import make_user_token
from tests.pg.helpers_t2 import (
    BOND,
    CASH,
    FD,
    GOLD,
    MF,
    NONE,
    NPS,
    OTHER,
    RD,
    SELL_DAY,
    SIP,
    STOCK,
    TODAY,
    add,
    asset,
    seed_masters,
)

pytestmark = pytest.mark.pg


@pytest.fixture
def env(pg_app, monkeypatch):
    """pg_app + seeded masters + one user; no network (history sync, NPS sync, today pinned)."""
    monkeypatch.setattr(nps_service, "sync_scheme_safely", lambda scheme_id: None)
    monkeypatch.setattr(sip_service, "ensure_history", lambda session, code: None)
    monkeypatch.setattr(sip_service, "today_ist", lambda: TODAY)
    with pg_app.session() as session:
        issuer_id = seed_masters(session)
        user, headers = make_user_token(session)
    pg_app.headers = headers
    pg_app.user_id = user.id
    pg_app.issuer_id = issuer_id
    return pg_app


def sell(env, slug, item_id, **overrides):
    body = {"date": SELL_DAY, "destination": NONE, **overrides}
    return env.client.post(f"/api/holdings/{slug}/{item_id}/sell", json=body, headers=env.headers)


def settle(env, slug, item_id, destination=None, **overrides):
    body = {"destination": destination or NONE, **overrides}
    return env.client.post(f"/api/holdings/{slug}/{item_id}/settle", json=body, headers=env.headers)


def cash_balance(env, cash_id) -> Decimal:
    return Decimal(str(asset(env.client, env.headers, "cash", cash_id)["balance"]))


# --- PUT (FOR UPDATE OF <model>, including models with a joined master) --------------------


@pytest.mark.parametrize(
    ("slug", "body", "change", "field"),
    [
        ("fd", FD, {"principal": 120000}, "principal"),
        ("nps", NPS, {"contributed": 45000}, "contributed"),
        ("stock", STOCK, {"quantity": 120}, "quantity"),
        ("mf", MF, {"units": 120, "invested_amount": 4800}, "units"),
        ("gold", GOLD, {"weight_grams": 12, "invested_amount": 60000}, "weight_grams"),
        ("cash", CASH, {"balance": 2500}, "balance"),
    ],
)
def test_put_runs_for_update_of_and_saves(env, slug, body, change, field):
    item_id = add(env.client, env.headers, slug, body)
    response = env.client.put(
        f"/api/assets/{slug}/{item_id}", json={**body, **change}, headers=env.headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Changes saved"
    assert float(asset(env.client, env.headers, slug, item_id)[field]) == float(change[field])


def test_put_fd_with_a_linked_issuer(env):
    body = {**FD, "issuer_id": env.issuer_id}
    item_id = add(env.client, env.headers, "fd", body)
    response = env.client.put(
        f"/api/assets/fd/{item_id}", json={**body, "principal": 130000}, headers=env.headers
    )
    assert response.status_code == 200, response.text
    assert asset(env.client, env.headers, "fd", item_id)["principal"] == 130000


def test_put_of_a_missing_or_foreign_row_is_404_not_a_server_error(env):
    assert env.client.put("/api/assets/nps/999", json=NPS, headers=env.headers).status_code == 404
    assert env.client.put("/api/assets/fd/999", json=FD, headers=env.headers).status_code == 404


# --- DELETE and restore (FOR UPDATE OF, include_deleted) ------------------------------------


@pytest.mark.parametrize(
    ("slug", "body"),
    [("fd", FD), ("nps", NPS), ("stock", STOCK), ("mf", MF), ("cash", CASH), ("gold", GOLD)],
)
def test_delete_then_restore(env, slug, body):
    item_id = add(env.client, env.headers, slug, body)
    url = f"/api/assets/{slug}/{item_id}"
    assert env.client.delete(url, headers=env.headers).status_code == 200
    assert env.client.get(url, headers=env.headers).status_code == 404
    assert env.client.delete(url, headers=env.headers).status_code == 404  # second delete: gone
    restored = env.client.post(f"{url}/restore", headers=env.headers)
    assert restored.status_code == 200, restored.text
    assert env.client.get(url, headers=env.headers).status_code == 200
    assert env.client.post(f"{url}/restore", headers=env.headers).status_code == 404  # live now


# --- Paid From (fundings FOR UPDATE on the cash account) -----------------------------------


def test_paid_from_debit_refund_and_restore(env):
    cash_id = add(env.client, env.headers, "cash", {**CASH, "balance": 100000})
    stock_id = add(env.client, env.headers, "stock", {**STOCK, "paid_from": {"cash_id": cash_id}})
    assert cash_balance(env, cash_id) == Decimal("95000")  # 100 x 50 taken off the account

    assert env.client.delete(f"/api/assets/stock/{stock_id}", headers=env.headers).status_code == 200
    assert cash_balance(env, cash_id) == Decimal("100000")  # refunded
    with env.session() as session:
        refunded = session.scalar(select(HoldingFunding.refunded_at))
        assert refunded is not None

    restored = env.client.post(f"/api/assets/stock/{stock_id}/restore", headers=env.headers)
    assert restored.status_code == 200, restored.text
    assert cash_balance(env, cash_id) == Decimal("95000")  # debited again


# --- sell, settle and undo -----------------------------------------------------------------


def test_sell_into_cash_then_undo(env):
    stock_id = add(env.client, env.headers, "stock", STOCK)
    cash_id = add(env.client, env.headers, "cash", CASH)
    dest = {"kind": "cash_existing", "cash_id": cash_id}
    response = sell(env, "stock", stock_id, quantity=40, price=80, charges=20, destination=dest)
    assert response.status_code == 201, response.text
    exit_id = response.json()["id"]
    assert cash_balance(env, cash_id) == Decimal("4180")
    assert asset(env.client, env.headers, "stock", stock_id)["quantity"] == 60

    undone = env.client.delete(f"/api/exits/{exit_id}", headers=env.headers)
    assert undone.status_code == 200, undone.text
    assert cash_balance(env, cash_id) == Decimal("1000")
    assert asset(env.client, env.headers, "stock", stock_id)["quantity"] == 100
    with env.session() as session:
        assert session.scalar(select(func.count()).select_from(HoldingExit)) == 0


@pytest.mark.parametrize(
    ("slug", "body", "extra"),
    [
        ("stock", STOCK, {"quantity": 100, "price": 80}),
        ("bond", BOND, {"quantity": 10, "price": 1000}),
        ("gold", GOLD, {"quantity": 10, "price": 6000}),
        ("mf", MF, {"quantity": 100, "price": 50}),
        ("other", OTHER, {"amount": 90000}),
    ],
)
def test_full_sale_of_each_type_closes_it_and_undo_reopens_it(env, slug, body, extra):
    item_id = add(env.client, env.headers, slug, body)
    response = sell(env, slug, item_id, **extra)
    assert response.status_code == 201, response.text
    assert response.json()["closed"] is True
    assert asset(env.client, env.headers, slug, item_id)["closed_on"] == SELL_DAY
    assert sell(env, slug, item_id, **extra).status_code == 409  # already sold

    undone = env.client.delete(f"/api/exits/{response.json()['id']}", headers=env.headers)
    assert undone.status_code == 200, undone.text
    assert asset(env.client, env.headers, slug, item_id)["closed_on"] is None


@pytest.mark.parametrize(("slug", "body"), [("fd", FD), ("rd", RD), ("bond", {**BOND, "maturity_date": "2025-06-01"})])
def test_settle_each_type_into_cash_then_undo(env, slug, body):
    item_id = add(env.client, env.headers, slug, body)
    cash_id = add(env.client, env.headers, "cash", CASH)
    dest = {"kind": "cash_existing", "cash_id": cash_id}
    response = settle(env, slug, item_id, dest)
    assert response.status_code == 201, response.text
    received = Decimal(str(response.json()["amount"]))
    assert received > 0 and cash_balance(env, cash_id) == Decimal("1000") + received
    assert settle(env, slug, item_id).status_code == 409  # one settlement only

    undone = env.client.delete(f"/api/exits/{response.json()['id']}", headers=env.headers)
    assert undone.status_code == 200, undone.text
    assert cash_balance(env, cash_id) == Decimal("1000")


def test_undo_of_an_exit_whose_holding_was_deleted_is_a_409(env):
    stock_id = add(env.client, env.headers, "stock", STOCK)
    sold = sell(env, "stock", stock_id, quantity=10, price=80).json()
    assert env.client.delete(f"/api/assets/stock/{stock_id}", headers=env.headers).status_code == 409
    with env.session() as session:  # legacy state: sold, then deleted before the delete guard existed
        session.execute(text("UPDATE stocks SET deleted_at = now() WHERE id = :i"), {"i": stock_id})
        session.commit()
    undone = env.client.delete(f"/api/exits/{sold['id']}", headers=env.headers)
    assert undone.status_code == 409 and undone.json()["message"] == "Holding not found"


def test_reinvest_from_an_exit_locks_the_exit_and_the_cash(env):
    """A new holding paid from the cash account a sale landed in (fundings.plan FOR UPDATE)."""
    stock_id = add(env.client, env.headers, "stock", STOCK)
    cash_id = add(env.client, env.headers, "cash", CASH)
    dest = {"kind": "cash_existing", "cash_id": cash_id}
    exit_id = sell(env, "stock", stock_id, quantity=100, price=80, destination=dest).json()["id"]
    assert cash_balance(env, cash_id) == Decimal("9000")
    paid = {"cash_id": cash_id, "from_exit_id": exit_id}
    small = {**STOCK, "name": "Reinvested Ltd", "quantity": 10, "paid_from": paid}  # costs 500
    new_id = add(env.client, env.headers, "stock", small)
    assert cash_balance(env, cash_id) == Decimal("8500")
    with env.session() as session:
        funding = session.scalar(select(HoldingFunding).where(HoldingFunding.holding_id == new_id))
        assert funding.from_exit_id == exit_id and funding.cash_holding_id == cash_id
    undone = env.client.delete(f"/api/exits/{exit_id}", headers=env.headers)
    assert undone.status_code == 409, undone.text  # the sale money was partly reinvested


# --- SIPs (sip.py FOR UPDATE OF MutualFund / MfSip) ----------------------------------------


def test_sip_create_and_post_due_post_instalments(env):
    response = env.client.post("/api/sips", json=SIP, headers=env.headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["instalments_added"] == 3  # 5 Jan, 5 Feb, 5 Mar
    fund_id, sip_id = body["mutual_fund_id"], body["id"]
    assert fund_id is not None

    with env.session() as session:
        before = session.scalar(
            select(func.count()).select_from(MFTransaction).where(MFTransaction.mutual_fund_id == fund_id)
        )
        posted = sip_service.post_due(session, date(2026, 5, 10))  # 5 Apr and 5 May fall due
        assert posted == {sip_id: 2}, "post_due swallows errors, so a silent failure shows as {}"
        again = sip_service.post_due(session, date(2026, 5, 10))
        assert again.get(sip_id, 0) == 0  # idempotent
        after = session.scalar(
            select(func.count()).select_from(MFTransaction).where(MFTransaction.mutual_fund_id == fund_id)
        )
        assert after == before + 2
        fund = session.get(MutualFund, fund_id)
        assert Decimal(str(fund.invested_amount)) == Decimal("25000")  # 5 x 5,000


def test_sip_lifecycle_endpoints_and_a_full_sale_of_its_fund(env):
    created = env.client.post("/api/sips", json=SIP, headers=env.headers).json()
    sip_id, fund_id = created["id"], created["mutual_fund_id"]
    base = f"/api/sips/{sip_id}"
    update = {"amount": 6000, "day_of_month": 6}
    assert env.client.put(base, json=update, headers=env.headers).status_code == 200
    assert env.client.post(f"{base}/pause", headers=env.headers).json()["status"] == "paused"
    assert env.client.post(f"{base}/resume", headers=env.headers).json()["status"] == "active"

    fund = asset(env.client, env.headers, "mf", fund_id)
    sold = sell(env, "mf", fund_id, quantity=fund["units"], price=50)
    assert sold.status_code == 201, sold.text
    undone = env.client.delete(f"/api/exits/{sold.json()['id']}", headers=env.headers)
    assert undone.status_code == 200, undone.text
    assert asset(env.client, env.headers, "mf", fund_id)["closed_on"] is None
    assert env.client.delete(base, headers=env.headers).status_code == 200  # DELETE /api/sips/{id}


def test_post_due_moves_a_running_sip_off_a_sold_fund_to_a_new_holding(env):
    created = env.client.post("/api/sips", json=SIP, headers=env.headers).json()
    sip_id, old_fund = created["id"], created["mutual_fund_id"]
    units = asset(env.client, env.headers, "mf", old_fund)["units"]
    assert sell(env, "mf", old_fund, quantity=units, price=50).status_code == 201
    with env.session() as session:
        # The sale does not decide whether the SIP runs; it stays active and moves on.
        assert session.get(MfSip, sip_id).status == "active"
        assert sip_service.post_due(session, date(2026, 4, 10)) == {sip_id: 1}
        session.expire_all()
        new_fund = session.get(MfSip, sip_id).mutual_fund_id
        assert new_fund is not None and new_fund != old_fund
        assert session.get(MutualFund, old_fund).closed_on is not None
        assert session.get(MutualFund, new_fund).closed_on is None


# --- CAS commit (FOR UPDATE OF MutualFund, in id order) ------------------------------------


def test_cas_commit_updates_an_existing_fund_and_adds_a_new_one(env):
    fund_id = add(env.client, env.headers, "mf", MF)

    def row(**changes):
        return {
            "action": "create", "holding_id": None, "scheme_code": 100, "scheme_name": "Fund A",
            "category": "equity", "units": 100, "avg_nav": 10, "invested_amount": 1000,
            "purchase_date": "2024-01-01", **changes,
        }  # fmt: skip

    response = env.client.post(
        "/api/import/cas/commit",
        json={"rows": [row(), row(action="update", holding_id=fund_id, units=20, avg_nav=50, invested_amount=1000)]},
        headers=env.headers,
    )
    assert response.status_code == 200, response.text
    assert (response.json()["created"], response.json()["updated"]) == (1, 1)
    assert asset(env.client, env.headers, "mf", fund_id)["units"] == 20
    with env.session() as session:
        assert session.scalar(select(func.count()).select_from(MutualFund)) == 2


def test_cas_commit_refuses_a_fund_with_a_sale_without_locking_it(env):
    fund_id = add(env.client, env.headers, "mf", MF)
    assert sell(env, "mf", fund_id, quantity=10, price=50).status_code == 201
    response = env.client.post(
        "/api/import/cas/commit",
        json={"rows": [{
            "action": "update", "holding_id": fund_id, "scheme_code": 100, "scheme_name": "Fund A",
            "category": "equity", "units": 20, "avg_nav": 50, "invested_amount": 1000,
            "purchase_date": "2024-01-01",
        }]},
        headers=env.headers,
    )  # fmt: skip
    assert response.status_code == 422
    assert "Sales are recorded for this fund here" in response.json()["description"]


# --- read_bind -----------------------------------------------------------------------------


def _pid_state(engine, pid) -> str | None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        return conn.execute(
            text("SELECT state FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid}
        ).scalar()


def test_read_bind_is_autocommit_and_a_normal_session_is_not(env):
    with env.session() as session:
        read = read_bind(session)
        assert read.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
        with read.connect() as conn:
            assert conn.connection.dbapi_connection.autocommit is True
            pid = conn.execute(text("SELECT pg_backend_pid()")).scalar()
            assert _pid_state(env.engine, pid) == "idle"  # no transaction left open after a read

        plain = session.connection()
        assert plain.connection.dbapi_connection.autocommit is False
        pid = plain.execute(text("SELECT pg_backend_pid()")).scalar()
        assert _pid_state(env.engine, pid) == "idle in transaction"
        session.rollback()


def test_read_only_endpoints_work_through_read_bind(env):
    add(env.client, env.headers, "stock", STOCK)
    add(env.client, env.headers, "cash", CASH)
    assert env.client.get("/api/dashboard", headers=env.headers).status_code == 200
    portfolio = env.client.get("/api/portfolio", headers=env.headers)
    assert portfolio.status_code == 200
    assert env.client.get("/api/holdings/stock", headers=env.headers).json()["total"] == 1


# --- soft delete: the global filter and include_deleted ------------------------------------


def test_soft_delete_filter_and_include_deleted(env):
    keep = add(env.client, env.headers, "cash", {**CASH, "name": "Kept"})
    gone = add(env.client, env.headers, "cash", {**CASH, "name": "Gone"})
    assert env.client.delete(f"/api/assets/cash/{gone}", headers=env.headers).status_code == 200

    with env.session() as session:
        assert [c.name for c in session.scalars(select(Cash).order_by(Cash.id))] == ["Kept"]
        assert list(session.scalars(select(Cash.id))) == [keep]
        everything = select(Cash.id).order_by(Cash.id).execution_options(include_deleted=True)
        assert list(session.scalars(everything)) == [keep, gone]
        # Subqueries over a soft-deleted table are filtered too.
        subquery = select(Cash.user_id).where(Cash.id == gone)
        assert session.scalar(select(func.count()).select_from(subquery.subquery())) == 0
        # Raw SQL is not covered by the filter (documented limit), and the row is really there.
        assert session.execute(text("SELECT count(*) FROM cash_holdings")).scalar() == 2
        deleted_at = session.execute(
            text("SELECT deleted_at FROM cash_holdings WHERE id = :id"), {"id": gone}
        ).scalar()
        assert deleted_at is not None  # func.now() was applied by the server

    listed = env.client.get("/api/deleted", headers=env.headers)
    assert listed.status_code == 200
    assert [(item["type"], item["id"]) for item in listed.json()] == [("cash", gone)]
    assert env.client.get("/api/holdings/cash", headers=env.headers).json()["total"] == 1
    assert env.client.post(f"/api/assets/cash/{gone}/restore", headers=env.headers).status_code == 200
    assert env.client.get("/api/holdings/cash", headers=env.headers).json()["total"] == 2


def test_soft_deleted_joined_master_holdings_stay_hidden(env):
    nps_id = add(env.client, env.headers, "nps", NPS)
    fd_id = add(env.client, env.headers, "fd", FD)
    env.client.delete(f"/api/assets/nps/{nps_id}", headers=env.headers)
    env.client.delete(f"/api/assets/fd/{fd_id}", headers=env.headers)
    with env.session() as session:
        assert session.scalars(select(Nps)).all() == []  # joined-master model, filtered
        assert session.scalars(select(FixedDeposit)).all() == []
        assert session.scalars(select(Stock)).all() == []
