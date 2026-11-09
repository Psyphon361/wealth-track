"""SIPs after a fund holding is sold: units never go into a sold holding (SPEC §8a).

A full sale keeps the row as a closed record (closed_on set, old units kept). The SIP keeps
running and its next instalment lands in an active holding of the same fund and platform, or in a
new one.
"""

from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import MFTransaction, MfSip, MutualFund
from app.services.sip import post_due
from tests.test_exits_api import asset, sell
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING, sc, start  # noqa: F401  (fixture)

SOLD_MESSAGE = "This holding has been sold"
SALE_DAY = "2026-03-10"


def session_of(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)()


def snapshot(engine, holding_id):
    with session_of(engine) as s:
        h = s.get(MutualFund, holding_id)
        txns = s.scalar(
            select(func.count()).select_from(MFTransaction).where(
                MFTransaction.mutual_fund_id == holding_id
            )
        )
        return (h.units, h.invested_amount, h.avg_nav, h.closed_on, h.purchase_date, txns)


def sell_all(sc, headers, holding_id):
    units = asset(sc, headers, "mf", holding_id)["units"]
    r = sell(sc, headers, "mf", holding_id, date=SALE_DAY, quantity=units, price=60)
    assert r.status_code == 201, r.json()
    return r.json()


def keep_running(engine, sip_id):
    """The sale itself must not decide whether the SIP runs; make sure it is active."""
    with session_of(engine) as s:
        s.get(MfSip, sip_id).status = "active"
        s.commit()


def running_sip_then_sold(sc, headers, engine, **holding):
    """A holding with a SIP that posted Jan to Mar, then the whole holding sold."""
    held = sc.post("/api/assets/mf", json={**HOLDING, **holding}, headers=headers).json()
    sip = start(sc, headers).json()
    assert sip["mutual_fund_id"] == held["id"] and sip["instalments_added"] == 3
    sell_all(sc, headers, held["id"])
    keep_running(engine, sip["id"])
    return held["id"], sip["id"]


def post(engine, day):
    with session_of(engine) as s:
        return post_due(s, day)


def sip_row(engine, sip_id):
    with session_of(engine) as s:
        return s.get(MfSip, sip_id)


# --- posting ------------------------------------------------------------------------------


def test_instalment_after_a_full_sale_starts_a_new_holding(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    before = snapshot(auth_engine, old_id)
    assert before[3] is not None  # closed

    assert post(auth_engine, date(2026, 4, 10)) == {sip_id: 1}
    sip = sip_row(auth_engine, sip_id)
    new_id = sip.mutual_fund_id
    assert new_id not in (None, old_id)
    assert sip.last_posted_on == date(2026, 4, 5)

    assert snapshot(auth_engine, old_id) == before  # the sold holding is left alone
    units, invested, avg_nav, closed_on, purchased, txns = snapshot(auth_engine, new_id)
    assert (units, invested, avg_nav) == (D("99.995"), D("5000"), D("50.0025"))
    assert closed_on is None and purchased == date(2026, 4, 5) and txns == 1
    with session_of(auth_engine) as s:
        (txn,) = s.scalars(select(MFTransaction).where(MFTransaction.mutual_fund_id == new_id))
        assert txn.sip_id == sip_id and txn.txn_date == date(2026, 4, 5)
        h = s.get(MutualFund, new_id)
        assert h.scheme_code == 100 and h.platform == "Groww"

    # The next instalment adds to the new holding; a re-run adds nothing.
    assert post(auth_engine, date(2026, 5, 10)) == {sip_id: 1}
    assert sip_row(auth_engine, sip_id).mutual_fund_id == new_id
    units, invested, avg_nav, *_rest, txns = snapshot(auth_engine, new_id)
    assert (units, invested, avg_nav, txns) == (D("199.990"), D("10000"), D("50.0025"), 2)
    assert post(auth_engine, date(2026, 5, 10)) == {sip_id: 0}
    assert snapshot(auth_engine, new_id)[1] == D("10000")
    assert snapshot(auth_engine, old_id) == before


def test_a_catch_up_run_puts_every_instalment_on_the_new_holding(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    before = snapshot(auth_engine, old_id)
    assert post(auth_engine, date(2026, 6, 10)) == {sip_id: 3}
    new_id = sip_row(auth_engine, sip_id).mutual_fund_id
    assert new_id != old_id
    units, invested, _avg, _closed, purchased, txns = snapshot(auth_engine, new_id)
    assert (units, invested, txns) == (D("299.985"), D("15000"), 3)
    assert purchased == date(2026, 4, 5)
    assert snapshot(auth_engine, old_id) == before


def test_an_active_holding_of_the_same_fund_and_platform_is_used(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    other = sc.post(
        "/api/assets/mf", json={**HOLDING, "platform": " groww ", "purchase_date": "2026-02-01"},
        headers=a,
    ).json()
    before = snapshot(auth_engine, old_id)

    assert post(auth_engine, date(2026, 4, 10)) == {sip_id: 1}
    assert sip_row(auth_engine, sip_id).mutual_fund_id == other["id"]
    held = asset(sc, a, "mf", other["id"])
    assert held["units"] == 199.995 and held["invested_amount"] == 9000
    with session_of(auth_engine) as s:
        assert s.scalar(select(func.count()).select_from(MutualFund)) == 2  # none created
        rows = s.scalars(
            select(MFTransaction).where(MFTransaction.mutual_fund_id == other["id"])
        ).all()
        assert sorted((t.sip_id is not None) for t in rows) == [False, True]  # opening + instalment
    assert snapshot(auth_engine, old_id) == before


def test_a_different_platform_is_not_mixed_in(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    other = sc.post("/api/assets/mf", json={**HOLDING, "platform": "Zerodha"}, headers=a).json()
    other_before = snapshot(auth_engine, other["id"])

    assert post(auth_engine, date(2026, 4, 10)) == {sip_id: 1}
    new_id = sip_row(auth_engine, sip_id).mutual_fund_id
    assert new_id not in (old_id, other["id"])
    assert snapshot(auth_engine, other["id"]) == other_before
    assert snapshot(auth_engine, new_id)[:2] == (D("99.995"), D("5000"))


def test_a_paused_sip_still_posts_nothing_after_a_sale(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    with session_of(auth_engine) as s:
        s.get(MfSip, sip_id).status = "paused"
        s.commit()
    before = snapshot(auth_engine, old_id)
    assert post(auth_engine, date(2026, 4, 10)) == {}
    assert snapshot(auth_engine, old_id) == before
    assert sip_row(auth_engine, sip_id).mutual_fund_id == old_id


# --- create -------------------------------------------------------------------------------


def test_create_when_the_only_holding_is_sold_starts_a_fresh_holding(sc, users, auth_engine):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sell_all(sc, a, held["id"])
    before = snapshot(auth_engine, held["id"])

    r = start(sc, a)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["mutual_fund_id"] not in (None, held["id"])
    assert body["instalments_added"] == 3
    assert snapshot(auth_engine, held["id"]) == before
    assert snapshot(auth_engine, body["mutual_fund_id"])[:2] == (D("299.985"), D("15000"))


def test_create_attaches_to_the_active_one_not_the_sold_one(sc, users, auth_engine):
    a = users[0]
    sold = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sell_all(sc, a, sold["id"])
    active = sc.post(
        "/api/assets/mf", json={**HOLDING, "purchase_date": "2025-07-01"}, headers=a
    ).json()
    assert start(sc, a).json()["mutual_fund_id"] == active["id"]


def test_an_explicit_sold_holding_is_refused(sc, users, auth_engine):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sell_all(sc, a, held["id"])
    r = start(sc, a, mutual_fund_id=held["id"])
    assert r.status_code == 422
    first = r.json()["detail"][0]
    assert first["msg"] == SOLD_MESSAGE
    assert list(first["loc"]) == ["body", "mutual_fund_id"]
    with session_of(auth_engine) as s:
        assert s.scalar(select(func.count()).select_from(MfSip)) == 0


# --- undo ---------------------------------------------------------------------------------


def test_undoing_the_sale_after_the_sip_moved_leaves_two_active_holdings(sc, users, auth_engine):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    assert post(auth_engine, date(2026, 4, 10)) == {sip_id: 1}
    new_id = sip_row(auth_engine, sip_id).mutual_fund_id
    assert new_id != old_id
    new_before = snapshot(auth_engine, new_id)

    (exit_row,) = sc.get(f"/api/holdings/mf/{old_id}/exits", headers=a).json()
    undone = sc.delete(f"/api/exits/{exit_row['id']}", headers=a)
    assert undone.status_code == 200, undone.json()

    old = snapshot(auth_engine, old_id)
    assert old[3] is None and old[0] == D("399.985")  # active again, its own units
    assert sip_row(auth_engine, sip_id).mutual_fund_id == new_id  # the SIP stays put
    assert snapshot(auth_engine, new_id) == new_before

    # The next instalment goes to the SIP's holding; the restored one is untouched.
    old_before = snapshot(auth_engine, old_id)
    assert post(auth_engine, date(2026, 5, 10)) == {sip_id: 1}
    assert snapshot(auth_engine, old_id) == old_before
    assert snapshot(auth_engine, new_id)[1] == D("10000")


# --- database checks ----------------------------------------------------------------------


def test_new_rows_satisfy_the_constraints_and_zero_units_are_refused(sc, users, auth_engine):
    a = users[0]
    _old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    post(auth_engine, date(2026, 5, 10))
    with session_of(auth_engine) as s:
        new = s.get(MutualFund, s.get(MfSip, sip_id).mutual_fund_id)
        assert new.units > 0 and new.avg_nav >= 0 and new.invested_amount >= 0
        for t in s.scalars(select(MFTransaction).where(MFTransaction.mutual_fund_id == new.id)):
            assert t.units > 0 and t.amount > 0
        s.add(
            MFTransaction(
                mutual_fund_id=new.id, txn_date=date(2026, 6, 1), kind="purchase",
                amount=D("100"), units=D("0"),
            )
        )
        with pytest.raises(IntegrityError, match="ck_mf_transactions_units_positive"):
            s.flush()
        s.rollback()
        s.add(
            MutualFund(
                user_id=new.user_id, scheme_name="X", scheme_code=100, platform="P",
                category="equity", units=D("0"), avg_nav=D("1"), invested_amount=D("1"),
                purchase_date=date(2026, 6, 1),
            )
        )
        with pytest.raises(IntegrityError, match="ck_mutual_funds_units_positive"):
            s.flush()
        s.rollback()


# --- deleted holdings ---------------------------------------------------------------------


def test_a_sold_then_deleted_holding_gets_a_new_holding_and_restore_is_safe(
    sc, users, auth_engine
):
    a = users[0]
    old_id, sip_id = running_sip_then_sold(sc, a, auth_engine)
    # The API refuses to delete a sold holding now; this is a legacy row deleted before that rule.
    assert sc.delete(f"/api/assets/mf/{old_id}", headers=a).status_code == 409
    with sessionmaker(bind=auth_engine)() as s:
        s.execute(
            text("UPDATE mutual_funds SET deleted_at = CURRENT_TIMESTAMP WHERE id = :i"), {"i": old_id}
        )
        s.commit()

    assert post(auth_engine, date(2026, 4, 10)) == {sip_id: 1}
    new_id = sip_row(auth_engine, sip_id).mutual_fund_id
    assert new_id not in (None, old_id)
    assert snapshot(auth_engine, new_id)[:2] == (D("99.995"), D("5000"))

    restored = sc.post(f"/api/assets/mf/{old_id}/restore", headers=a)
    assert restored.status_code == 200, restored.json()
    assert sip_row(auth_engine, sip_id).mutual_fund_id == new_id  # stays on the new one

    old_before = snapshot(auth_engine, old_id)
    assert post(auth_engine, date(2026, 5, 10)) == {sip_id: 1}
    assert sip_row(auth_engine, sip_id).mutual_fund_id == new_id
    assert snapshot(auth_engine, old_id) == old_before
    assert snapshot(auth_engine, new_id)[1] == D("10000")


def test_an_active_holding_deleted_keeps_the_sip_running_and_restore_gives_two(
    sc, users, auth_engine
):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sip = start(sc, a).json()
    assert sip["mutual_fund_id"] == held["id"]
    assert sc.delete(f"/api/assets/mf/{held['id']}", headers=a).status_code == 200
    with session_of(auth_engine) as s:
        before_units = s.scalars(
            select(MutualFund).where(MutualFund.id == held["id"]).execution_options(include_deleted=True)
        ).one().units

    assert post(auth_engine, date(2026, 4, 10)) == {sip["id"]: 1}
    new_id = sip_row(auth_engine, sip["id"]).mutual_fund_id
    assert new_id not in (None, held["id"])

    assert sc.post(f"/api/assets/mf/{held['id']}/restore", headers=a).status_code == 200
    with session_of(auth_engine) as s:
        active = s.scalars(select(MutualFund).where(MutualFund.closed_on.is_(None))).all()
        assert {h.id for h in active} == {held["id"], new_id}
        assert s.get(MutualFund, held["id"]).units == before_units
    assert sip_row(auth_engine, sip["id"]).mutual_fund_id == new_id


def test_a_paused_sip_with_a_deleted_holding_posts_nothing(sc, users, auth_engine):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sip = start(sc, a).json()
    assert sc.delete(f"/api/assets/mf/{held['id']}", headers=a).status_code == 200
    with session_of(auth_engine) as s:
        s.get(MfSip, sip["id"]).status = "paused"
        s.commit()
    assert post(auth_engine, date(2026, 4, 10)) == {}
    assert sip_row(auth_engine, sip["id"]).mutual_fund_id == held["id"]
