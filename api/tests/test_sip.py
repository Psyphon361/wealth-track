"""SIP maths (pure) and instalment posting (SQLite, no network)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.db import Base
from app.models import (
    MFMaster,
    MFNavHistory,
    MFNavHistorySync,
    MFNavLatest,
    MFTransaction,
    MfSip,
    MfSipSkip,
    MutualFund,
)
from app.services import nav_history
from app.services import sip as sip_service
from app.services.sip import (
    due_dates,
    first_due_on_or_after,
    format_inr,
    next_due,
    ordinal,
    post_due,
    units_for,
)

D = Decimal
REAL_ENSURE_HISTORY = sip_service.ensure_history  # the fixture replaces it with a recorder

# --- due dates ----------------------------------------------------------------------------


def test_first_due_on_or_after():
    assert first_due_on_or_after(5, date(2026, 1, 3)) == date(2026, 1, 5)
    assert first_due_on_or_after(5, date(2026, 1, 5)) == date(2026, 1, 5)
    assert first_due_on_or_after(5, date(2026, 1, 6)) == date(2026, 2, 5)
    assert first_due_on_or_after(1, date(2026, 1, 31)) == date(2026, 2, 1)
    assert first_due_on_or_after(28, date(2025, 12, 29)) == date(2026, 1, 28)


def test_due_dates_month_ends_and_day_28():
    # Started on a month end: the first instalment is the next month's due day.
    assert due_dates(28, date(2026, 1, 31), date(2026, 4, 30)) == [
        date(2026, 2, 28),
        date(2026, 3, 28),
        date(2026, 4, 28),
    ]
    assert due_dates(28, date(2026, 1, 28), date(2026, 1, 28)) == [date(2026, 1, 28)]
    # February has a 28th, so the 28th never needs clamping.
    assert due_dates(28, date(2028, 2, 1), date(2028, 3, 1)) == [date(2028, 2, 28)]


def test_due_dates_cross_year_and_until_is_inclusive():
    assert due_dates(15, date(2025, 11, 1), date(2026, 1, 15)) == [
        date(2025, 11, 15),
        date(2025, 12, 15),
        date(2026, 1, 15),
    ]
    assert due_dates(15, date(2025, 11, 1), date(2026, 1, 14)) == [
        date(2025, 11, 15),
        date(2025, 12, 15),
    ]


def test_due_dates_end_date_inclusive_and_nothing_before_post_from():
    dates = due_dates(5, date(2026, 1, 1), date(2026, 12, 31), end_date=date(2026, 3, 5))
    assert dates == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]
    assert due_dates(5, date(2026, 1, 1), date(2026, 12, 31), end_date=date(2026, 3, 4))[-1] == date(
        2026, 2, 5
    )
    assert due_dates(5, date(2026, 3, 6), date(2026, 3, 31)) == []


def test_due_dates_skips_and_after():
    skipped = {date(2026, 2, 5)}
    assert due_dates(5, date(2026, 1, 1), date(2026, 3, 31), skipped=skipped) == [
        date(2026, 1, 5),
        date(2026, 3, 5),
    ]
    assert due_dates(5, date(2026, 1, 1), date(2026, 3, 31), after=date(2026, 2, 5)) == [
        date(2026, 3, 5)
    ]


def test_due_dates_pause_and_resume_skip_paused_months():
    # Resuming moves post_from forward; the paused months never come back.
    resumed_from = next_due(5, date(2026, 5, 20), date(2026, 5, 20), None, date(2026, 2, 5))
    assert resumed_from == date(2026, 6, 5)
    assert due_dates(5, resumed_from, date(2026, 7, 31), after=date(2026, 2, 5)) == [
        date(2026, 6, 5),
        date(2026, 7, 5),
    ]


def test_next_due():
    assert next_due(5, date(2026, 3, 10), date(2026, 1, 5)) == date(2026, 4, 5)
    assert next_due(5, date(2026, 3, 5), date(2026, 1, 5)) == date(2026, 3, 5)
    # Future start: the first instalment is the next date.
    assert next_due(5, date(2026, 3, 10), date(2026, 5, 5)) == date(2026, 5, 5)
    # Already posted today: next month.
    assert next_due(5, date(2026, 3, 5), date(2026, 1, 5), None, date(2026, 3, 5)) == date(2026, 4, 5)
    # Ended.
    assert next_due(5, date(2026, 3, 10), date(2026, 1, 5), date(2026, 4, 1)) is None
    assert next_due(5, date(2026, 3, 10), date(2026, 1, 5), date(2026, 4, 5)) == date(2026, 4, 5)


# --- money maths --------------------------------------------------------------------------


def test_units_stamp_duty():
    assert units_for(D("5000"), D("50")) == D("99.995")


def test_units_rounded_to_three_places():
    assert units_for(D("1000"), D("33.3333")) == D("29.999")  # 29.99853
    assert units_for(D("2500"), D("37.1234")) == D("67.340")  # 67.33960
    assert units_for(D("100"), D("40")) == D("2.500")  # 2.499875


def test_format_inr_and_ordinal():
    assert format_inr(D("100")) == "₹100"
    assert format_inr(D("5000")) == "₹5,000"
    assert format_inr(D("125000")) == "₹1,25,000"
    assert format_inr(D("1234567.5")) == "₹12,34,567.50"
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 28)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "28th",
    ]  # fmt: skip
    assert sip_service.schedule_text(D("5000"), 5) == "₹5,000 on the 5th of every month"


# --- posting ------------------------------------------------------------------------------

USER = 1
CODE = 100


@pytest.fixture
def sdb(db_session, auth_engine, monkeypatch):
    Base.metadata.create_all(
        auth_engine,
        tables=[
            m.__table__
            for m in (
                MFMaster, MFNavHistory, MFNavHistorySync, MFNavLatest, MutualFund,
                MFTransaction, MfSip, MfSipSkip,
            )
        ],
    )  # fmt: skip
    for code, name, category in ((CODE, "Fund A - Direct Growth", "equity"), (101, "Fund B", "debt")):
        db_session.add(MFMaster(scheme_code=code, name=name, category=category, is_active=True))
    db_session.commit()
    calls = []
    monkeypatch.setattr(sip_service, "ensure_history", lambda session, code: calls.append(code))
    db_session.fetches = calls
    return db_session


def add_nav(session, code, day, nav="50", synced_from=date(2025, 1, 1)):
    session.add(MFNavHistory(scheme_code=code, nav_date=day, nav=D(nav)))
    if session.get(MFNavHistorySync, code) is None:
        session.add(
            MFNavHistorySync(
                scheme_code=code, first_date=synced_from, last_date=day,
                fetched_at=datetime.now(timezone.utc),
            )
        )  # fmt: skip
    session.commit()


def add_navs(session, code, days, nav="50"):
    for day in days:
        add_nav(session, code, day, nav)


def new_sip(session, **kw):
    fields = dict(
        user_id=USER, scheme_code=CODE, platform="Groww", amount=D("5000"), day_of_month=5,
        start_date=date(2026, 1, 5), post_from=date(2026, 1, 5), status="active",
    )  # fmt: skip
    fields.update(kw)
    sip = MfSip(**fields)
    session.add(sip)
    session.commit()
    return sip


def txns_of(session, holding_id):
    return list(
        session.scalars(
            select(MFTransaction)
            .where(MFTransaction.mutual_fund_id == holding_id)
            .order_by(MFTransaction.txn_date, MFTransaction.id)
        )
    )


def test_creates_holding_on_first_instalment(sdb):
    add_navs(sdb, CODE, [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)])
    sip = new_sip(sdb)
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 3}
    holding = sdb.get(MutualFund, sip.mutual_fund_id)
    assert holding.scheme_name == "Fund A - Direct Growth"
    assert holding.category == "equity"
    assert holding.platform == "Groww"
    assert holding.scheme_code == CODE
    assert holding.purchase_date == date(2026, 1, 5)
    assert holding.units == D("299.985")
    assert holding.invested_amount == D("15000")
    assert holding.avg_nav == D("50.0025")  # 15000 / 299.985
    assert sip.last_posted_on == date(2026, 3, 5)
    rows = txns_of(sdb, holding.id)
    assert [(t.txn_date, t.kind, t.amount, t.units, t.sip_id) for t in rows] == [
        (date(2026, 1, 5), "purchase", D("5000"), D("99.995"), sip.id),
        (date(2026, 2, 5), "purchase", D("5000"), D("99.995"), sip.id),
        (date(2026, 3, 5), "purchase", D("5000"), D("99.995"), sip.id),
    ]


def test_holiday_uses_next_business_day_nav(sdb):
    # 4 Jan 2026 is a Sunday: no NAV that day, so Monday's NAV is used.
    add_nav(sdb, CODE, date(2026, 1, 2), "40")
    add_nav(sdb, CODE, date(2026, 1, 5), "50")
    sip = new_sip(sdb, day_of_month=4, post_from=date(2026, 1, 4), start_date=date(2026, 1, 4))
    assert post_due(sdb, date(2026, 1, 6)) == {sip.id: 1}
    (txn,) = txns_of(sdb, sip.mutual_fund_id)
    assert txn.txn_date == date(2026, 1, 5)
    assert txn.units == D("99.995")
    assert sip.last_posted_on == date(2026, 1, 4)  # the due date, not the NAV date


def test_does_not_use_an_earlier_or_latest_nav(sdb):
    add_nav(sdb, CODE, date(2026, 1, 2), "40")
    sdb.add(MFNavLatest(scheme_code=CODE, nav=D("60"), nav_date=date(2026, 3, 1)))
    sdb.commit()
    sip = new_sip(sdb, day_of_month=4, post_from=date(2026, 1, 4))
    # Nothing is published on or after 4 Jan yet (latest is a later, unrelated date).
    assert post_due(sdb, date(2026, 1, 6)) == {sip.id: 0}
    assert sip.mutual_fund_id is None and sip.last_posted_on is None
    assert sdb.fetches == [CODE]  # it asked for fresh history


def test_latest_nav_used_when_it_is_exactly_the_due_date(sdb):
    sdb.add(MFNavLatest(scheme_code=CODE, nav=D("25"), nav_date=date(2026, 3, 5)))
    sdb.commit()
    sip = new_sip(sdb, post_from=date(2026, 3, 5), start_date=date(2026, 3, 5))
    assert post_due(sdb, date(2026, 3, 5)) == {sip.id: 1}
    (txn,) = txns_of(sdb, sip.mutual_fund_id)
    assert txn.units == D("199.990")  # 5000 * 0.99995 / 25


def test_due_date_older_than_stored_history_takes_the_first_nav(sdb):
    # History starts 1 Jun 2026; an instalment due before that can't get a better NAV.
    sdb.add(MFNavHistory(scheme_code=CODE, nav_date=date(2026, 6, 1), nav=D("50")))
    sdb.add(
        MFNavHistorySync(
            scheme_code=CODE, first_date=date(2026, 6, 1), last_date=date(2026, 6, 1),
            fetched_at=datetime.now(timezone.utc),
        )
    )  # fmt: skip
    sdb.commit()
    assert sip_service.nav_for_due(sdb, CODE, date(2026, 1, 5)) == (date(2026, 6, 1), D("50"))


def test_a_nav_far_after_the_due_date_is_a_gap_not_a_holiday(sdb):
    add_nav(sdb, CODE, date(2026, 1, 2))
    add_nav(sdb, CODE, date(2026, 3, 5))  # nothing for six weeks in between
    assert sip_service.nav_for_due(sdb, CODE, date(2026, 2, 5)) is None
    assert sip_service.nav_for_due(sdb, CODE, date(2026, 3, 1)) == (date(2026, 3, 5), D("50"))


def test_stops_at_first_missing_nav_and_resumes_next_run(sdb):
    add_nav(sdb, CODE, date(2026, 1, 5))
    add_nav(sdb, CODE, date(2026, 3, 5))  # February's NAV is missing
    sip = new_sip(sdb)
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 1}
    assert sip.last_posted_on == date(2026, 1, 5)
    add_nav(sdb, CODE, date(2026, 2, 5))
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 2}
    assert [t.txn_date for t in txns_of(sdb, sip.mutual_fund_id)] == [
        date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5),
    ]  # fmt: skip


def test_idempotent_rerun(sdb):
    add_navs(sdb, CODE, [date(2026, 1, 5), date(2026, 2, 5)])
    sip = new_sip(sdb)
    assert post_due(sdb, date(2026, 2, 10)) == {sip.id: 2}
    assert post_due(sdb, date(2026, 2, 10)) == {sip.id: 0}
    assert post_due(sdb, date(2026, 2, 28)) == {sip.id: 0}
    assert len(txns_of(sdb, sip.mutual_fund_id)) == 2
    assert sdb.get(MutualFund, sip.mutual_fund_id).invested_amount == D("10000")


def test_unique_key_blocks_a_double_post(sdb):
    add_nav(sdb, CODE, date(2026, 1, 5))
    sip = new_sip(sdb)
    post_due(sdb, date(2026, 1, 10))
    # Even with last_posted_on lost, the (sip_id, txn_date) key refuses the repeat and the
    # failure is contained.
    sip.last_posted_on = None
    sdb.commit()
    assert post_due(sdb, date(2026, 1, 10)) == {sip.id: 0}
    assert len(txns_of(sdb, sip.mutual_fund_id)) == 1
    assert sdb.get(MutualFund, sip.mutual_fund_id).invested_amount == D("5000")


def test_existing_holding_without_transactions_gets_an_opening_txn(sdb):
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A - Direct Growth", scheme_code=CODE, platform="Groww",
        category="equity", units=D("100"), avg_nav=D("40"), invested_amount=D("4000"),
        purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    add_nav(sdb, CODE, date(2026, 1, 5))
    sip = new_sip(sdb, mutual_fund_id=holding.id)
    assert post_due(sdb, date(2026, 1, 10)) == {sip.id: 1}
    rows = txns_of(sdb, holding.id)
    assert [(t.txn_date, t.amount, t.units, t.sip_id) for t in rows] == [
        (date(2025, 6, 1), D("4000"), D("100"), None),
        (date(2026, 1, 5), D("5000"), D("99.995"), sip.id),
    ]
    assert holding.units == D("199.995")
    assert holding.invested_amount == D("9000")
    assert holding.avg_nav == D("45.0011")  # 9000 / 199.995
    assert holding.purchase_date == date(2025, 6, 1)  # unchanged


def test_existing_holding_with_transactions_gets_no_opening_txn(sdb):
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A", scheme_code=CODE, platform="Groww", category="equity",
        units=D("100"), avg_nav=D("40"), invested_amount=D("4000"), purchase_date=date(2025, 6, 1),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    sdb.add(
        MFTransaction(
            mutual_fund_id=holding.id, txn_date=date(2025, 6, 1), kind="purchase",
            amount=D("4000"), units=D("100"),
        )
    )  # fmt: skip
    sdb.commit()
    add_nav(sdb, CODE, date(2026, 1, 5))
    sip = new_sip(sdb, mutual_fund_id=holding.id)
    post_due(sdb, date(2026, 1, 10))
    assert len(txns_of(sdb, holding.id)) == 2


def test_paused_and_stopped_post_nothing(sdb):
    add_nav(sdb, CODE, date(2026, 1, 5))
    paused = new_sip(sdb, status="paused")
    stopped = new_sip(sdb, status="stopped")
    assert post_due(sdb, date(2026, 1, 10)) == {}
    assert paused.mutual_fund_id is None and stopped.mutual_fund_id is None
    assert sdb.scalar(select(func.count()).select_from(MutualFund)) == 0


def test_future_post_from_waits(sdb):
    add_nav(sdb, CODE, date(2026, 1, 5))
    new_sip(sdb, post_from=date(2026, 5, 5))
    assert post_due(sdb, date(2026, 1, 10)) == {}


def test_deleted_holding_is_skipped(sdb):
    holding = MutualFund(
        user_id=USER, scheme_name="Fund A", scheme_code=CODE, platform="Groww", category="equity",
        units=D("100"), avg_nav=D("40"), invested_amount=D("4000"), purchase_date=date(2025, 6, 1),
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )  # fmt: skip
    sdb.add(holding)
    sdb.commit()
    add_nav(sdb, CODE, date(2026, 1, 5))
    sip = new_sip(sdb, mutual_fund_id=holding.id)
    assert post_due(sdb, date(2026, 1, 10)) == {sip.id: 0}
    assert sdb.scalar(select(func.count()).select_from(MFTransaction)) == 0
    assert sdb.scalar(select(func.count()).select_from(MutualFund).execution_options(include_deleted=True)) == 1


def test_purged_holding_does_not_come_back(sdb):
    add_nav(sdb, CODE, date(2026, 2, 5))
    sip = new_sip(sdb, mutual_fund_id=None, last_posted_on=date(2026, 1, 5))
    assert post_due(sdb, date(2026, 2, 10)) == {sip.id: 0}
    assert sdb.scalar(select(func.count()).select_from(MutualFund)) == 0


def test_skipped_date_is_not_posted(sdb):
    add_navs(sdb, CODE, [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)])
    sip = new_sip(sdb)
    sdb.add(MfSipSkip(sip_id=sip.id, due_date=date(2026, 2, 5)))
    sdb.commit()
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 2}
    assert [t.txn_date for t in txns_of(sdb, sip.mutual_fund_id)] == [
        date(2026, 1, 5), date(2026, 3, 5),
    ]  # fmt: skip


def test_end_date_stops_posting(sdb):
    add_navs(sdb, CODE, [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)])
    sip = new_sip(sdb, end_date=date(2026, 2, 5))
    assert post_due(sdb, date(2026, 3, 10)) == {sip.id: 2}


def test_sip_ids_filter(sdb):
    add_nav(sdb, CODE, date(2026, 1, 5))
    add_nav(sdb, 101, date(2026, 1, 5))
    one = new_sip(sdb)
    two = new_sip(sdb, scheme_code=101)
    assert post_due(sdb, date(2026, 1, 10), [two.id]) == {two.id: 1}
    assert one.mutual_fund_id is None


def test_one_failing_sip_does_not_stop_the_others(sdb, monkeypatch):
    add_nav(sdb, CODE, date(2026, 1, 5))
    add_nav(sdb, 101, date(2026, 1, 5))
    bad = new_sip(sdb)
    good = new_sip(sdb, scheme_code=101)
    real = sip_service.nav_for_due

    def flaky(session, scheme_code, due):
        if scheme_code == CODE:
            raise RuntimeError("boom")
        return real(session, scheme_code, due)

    monkeypatch.setattr(sip_service, "nav_for_due", flaky)
    assert post_due(sdb, date(2026, 1, 10)) == {bad.id: 0, good.id: 1}
    assert bad.last_posted_on is None
    assert good.last_posted_on == date(2026, 1, 5)


def test_post_due_safely_never_raises(sdb, monkeypatch):
    def boom(session, today, sip_ids=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(sip_service, "post_due", boom)
    assert sip_service.post_due_safely(sdb) == 0


def test_post_due_safely_counts_instalments(sdb, monkeypatch):
    add_nav(sdb, CODE, date(2026, 1, 5))
    new_sip(sdb)
    monkeypatch.setattr(sip_service, "today_ist", lambda: date(2026, 1, 10))
    assert sip_service.post_due_safely(sdb) == 1


# --- history fetch ------------------------------------------------------------------------


def test_ensure_history_fetches_when_never_synced(sdb, monkeypatch):
    calls = []
    monkeypatch.setattr(sip_service, "ensure_history", REAL_ENSURE_HISTORY)
    monkeypatch.setattr(nav_history, "fetch_mfapi", lambda code: calls.append(("fetch", code)) or [])
    monkeypatch.setattr(
        nav_history, "store_history", lambda s, code, rows, today, now: calls.append(("store", code))
    )
    sip_service.ensure_history(sdb, CODE)
    assert calls == [("fetch", CODE), ("store", CODE)]


def test_ensure_history_skips_a_fresh_sync_and_refetches_a_stale_one(sdb, monkeypatch):
    calls = []
    monkeypatch.setattr(sip_service, "ensure_history", REAL_ENSURE_HISTORY)
    monkeypatch.setattr(nav_history, "fetch_mfapi", lambda code: calls.append(code) or [])
    monkeypatch.setattr(nav_history, "store_history", lambda *a: None)
    sdb.add(
        MFNavHistorySync(
            scheme_code=CODE, first_date=date(2025, 1, 1), last_date=date(2026, 1, 1),
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )  # fmt: skip
    sdb.commit()
    sip_service.ensure_history(sdb, CODE)
    assert calls == []
    sdb.get(MFNavHistorySync, CODE).fetched_at = datetime.now(timezone.utc) - timedelta(hours=7)
    sdb.commit()
    sip_service.ensure_history(sdb, CODE)
    assert calls == [CODE]


def test_ensure_history_swallows_fetch_errors(sdb, monkeypatch):
    monkeypatch.setattr(sip_service, "ensure_history", REAL_ENSURE_HISTORY)

    def boom(code):
        raise nav_history.NavSourceError("down")

    monkeypatch.setattr(nav_history, "fetch_mfapi", boom)
    sip_service.ensure_history(sdb, CODE)  # does not raise
