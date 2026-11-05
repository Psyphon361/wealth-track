"""SIP endpoints: shapes, errors, user scoping, MF holdings additions (SQLite, no network)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import MFMaster, MFNavHistory, MFNavHistorySync, MFTransaction, MfSip, MfSipSkip
from app.services import sip as sip_service
from tests.test_scoping import client, users  # noqa: F401

TODAY = date(2026, 3, 10)
BODY = {
    "scheme_code": 100, "platform": "Groww", "amount": 5000, "day_of_month": 5,
    "start_date": "2026-01-05", "include_past": True,
}  # fmt: skip
HOLDING = {
    "scheme_name": "Fund A", "scheme_code": 100, "platform": "Groww", "category": "equity",
    "units": 100, "avg_nav": 40, "invested_amount": 4000, "purchase_date": "2025-06-01",
}  # fmt: skip


@pytest.fixture
def sc(client, auth_engine, monkeypatch):  # noqa: F811
    """Client with the MF master, a year of daily NAVs (50) and a fixed 'today'."""
    for table in (MFMaster, MFNavHistory, MFNavHistorySync):
        table.__table__.create(auth_engine, checkfirst=True)
    with sessionmaker(bind=auth_engine)() as session:
        session.add(MFMaster(scheme_code=100, name="Fund A - Direct Growth", category="equity", is_active=True))
        session.add(MFMaster(scheme_code=101, name="Fund B - Retired", category="debt", is_active=False))
        session.add(MFMaster(scheme_code=102, name="Fund C - Direct Growth", category="index", is_active=True))
        for code in (100, 102):
            day = date(2024, 12, 1)
            while day <= date(2026, 7, 31):
                session.add(MFNavHistory(scheme_code=code, nav_date=day, nav=Decimal("50")))
                day += timedelta(days=1)
            session.add(
                MFNavHistorySync(
                    scheme_code=code, first_date=date(2024, 12, 1), last_date=date(2026, 7, 31),
                    fetched_at=datetime.now(timezone.utc),
                )
            )  # fmt: skip
        session.commit()
    monkeypatch.setattr(sip_service, "ensure_history", lambda session, code: None)
    monkeypatch.setattr(sip_service, "today_ist", lambda: TODAY)
    return client


def start(sc, headers, confirm=False, **overrides):
    url = "/api/sips?confirm_duplicate=true" if confirm else "/api/sips"
    return sc.post(url, json={**BODY, **overrides}, headers=headers)


def set_today(monkeypatch, day):
    monkeypatch.setattr(sip_service, "today_ist", lambda: day)


# --- create -------------------------------------------------------------------------------


def test_create_posts_past_instalments_and_reports_the_count(sc, users):
    a = users[0]
    r = start(sc, a)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["message"] == "SIP started · 3 instalments added"
    assert body["description"] == "Fund A - Direct Growth · ₹5,000 on the 5th of every month"
    assert body["scheme_code"] == 100 and body["fund_name"] == "Fund A - Direct Growth"
    assert body["platform"] == "Groww" and body["amount"] == 5000 and body["day_of_month"] == 5
    assert body["start_date"] == "2026-01-05" and body["end_date"] is None
    assert body["status"] == "active" and body["next_date"] == "2026-04-05"
    assert body["skipped_dates"] == []
    assert body["instalments_added"] == 3 and body["invested_via_sip"] == 15000
    assert body["mutual_fund_id"] is not None

    holding = sc.get(f"/api/assets/mf/{body['mutual_fund_id']}", headers=a).json()
    assert holding["scheme_name"] == "Fund A - Direct Growth"
    assert holding["platform"] == "Groww" and holding["category"] == "equity"
    assert holding["units"] == 299.985 and holding["invested_amount"] == 15000
    assert holding["avg_nav"] == 50.0025 and holding["purchase_date"] == "2026-01-05"


def test_create_one_instalment_message_is_singular(sc, users):
    r = start(sc, users[0], start_date="2026-03-05")
    assert r.json()["message"] == "SIP started · 1 instalment added"


def test_include_past_false_starts_at_the_next_due_date(sc, users):
    r = start(sc, users[0], include_past=False)
    assert r.status_code == 201
    body = r.json()
    assert body["message"] == "SIP started"
    assert body["instalments_added"] == 0 and body["mutual_fund_id"] is None
    assert body["next_date"] == "2026-04-05"


def test_include_past_false_with_a_due_date_today_posts_today(sc, users):
    # Today is 10 Mar, so day 10 is due today.
    r = start(sc, users[0], include_past=False, day_of_month=10)
    assert r.json()["instalments_added"] == 1


def test_future_start_date_waits(sc, users):
    r = start(sc, users[0], start_date="2026-05-01")
    body = r.json()
    assert body["instalments_added"] == 0 and body["next_date"] == "2026-05-05"


def test_attaches_to_the_single_holding_of_same_scheme_and_platform(sc, users):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    r = start(sc, a, platform=" groww ")
    assert r.json()["mutual_fund_id"] == held["id"]
    after = sc.get(f"/api/assets/mf/{held['id']}", headers=a).json()
    assert after["units"] == 399.985 and after["invested_amount"] == 19000
    # The holding's earlier units become an opening purchase, then the three instalments.
    page = sc.get(f"/api/holdings/mf/{held['id']}/transactions", headers=a).json()
    assert page["total"] == 4
    assert [t["sip"] for t in page["items"]] == [True, True, True, False]
    assert page["items"][-1]["date"] == "2025-06-01" and page["items"][-1]["amount"] == 4000


def test_two_matching_holdings_means_a_new_one(sc, users):
    a = users[0]
    first = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    second = sc.post(
        "/api/assets/mf", json={**HOLDING, "purchase_date": "2025-07-01"}, headers=a
    ).json()
    r = start(sc, a).json()
    assert r["mutual_fund_id"] not in (first["id"], second["id"])


def test_other_platform_means_a_new_holding(sc, users):
    a = users[0]
    held = sc.post("/api/assets/mf", json={**HOLDING, "platform": "Zerodha"}, headers=a).json()
    assert start(sc, a).json()["mutual_fund_id"] != held["id"]


def test_explicit_holding_must_be_a_same_fund_of_the_user(sc, users):
    a, _, b, _ = users
    other_fund = sc.post("/api/assets/mf", json={**HOLDING, "scheme_code": 102}, headers=a).json()
    r = start(sc, a, mutual_fund_id=other_fund["id"])
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "This holding is a different fund"
    theirs = sc.post("/api/assets/mf", json=HOLDING, headers=b).json()
    r = start(sc, a, mutual_fund_id=theirs["id"])
    assert r.status_code == 404
    assert r.json()["message"] == "Holding not found"
    r = start(sc, a, mutual_fund_id=99999)
    assert r.status_code == 404


def test_explicit_holding_is_used(sc, users):
    a = users[0]
    first = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    sc.post("/api/assets/mf", json={**HOLDING, "purchase_date": "2025-07-01"}, headers=a)
    assert start(sc, a, mutual_fund_id=first["id"]).json()["mutual_fund_id"] == first["id"]


def test_duplicate_sip_warns_unless_confirmed(sc, users):
    a = users[0]
    first = start(sc, a).json()
    r = start(sc, a)
    assert r.status_code == 409
    body = r.json()
    assert body["message"] == "This looks like a SIP you already have"
    assert body["description"] == (
        "Fund A - Direct Growth · ₹5,000 on the 5th of every month is already running."
    )
    assert body["duplicates"] == [{"id": first["id"], "name": "Fund A - Direct Growth"}]
    assert len(sc.get("/api/sips", headers=a).json()) == 1

    assert start(sc, a, confirm=True).status_code == 201
    assert len(sc.get("/api/sips", headers=a).json()) == 2


def test_not_a_duplicate_when_amount_day_or_status_differ(sc, users):
    a = users[0]
    first = start(sc, a).json()
    assert start(sc, a, amount=6000).status_code == 201
    assert start(sc, a, day_of_month=6).status_code == 201
    sc.post(f"/api/sips/{first['id']}/pause", headers=a)
    assert start(sc, a).status_code == 201  # the same SIP is paused, not active


def test_duplicate_check_is_per_user(sc, users):
    a, _, b, _ = users
    start(sc, a)
    assert start(sc, b).status_code == 201


@pytest.mark.parametrize(
    ("overrides", "field", "message"),
    [
        ({"amount": 99}, "amount", "Must be at least ₹100"),
        ({"amount": 0}, "amount", "Must be at least ₹100"),
        ({"amount": 1000000001}, "amount", "Must be at most ₹100 crore"),
        ({"amount": 100.505}, "amount", "Up to 2 decimal places allowed"),
        ({"day_of_month": 0}, "day_of_month", "Day must be between 1 and 28"),
        ({"day_of_month": 29}, "day_of_month", "Day must be between 1 and 28"),
        ({"day_of_month": 5.5}, "day_of_month", "Must be a whole number"),
        ({"start_date": "1989-12-31"}, "start_date", "Date must be on or after 1 Jan 1990"),
        ({"start_date": "2999-01-01"}, "start_date", "Date can be at most 1 year in the future"),
        ({"scheme_code": 999999}, "scheme_code", "Select a scheme from the list"),
        ({"scheme_code": 101}, "scheme_code", "This scheme is no longer active"),
        ({"platform": "  "}, "platform", "Required"),
    ],
)
def test_create_validation(sc, users, overrides, field, message):
    r = start(sc, users[0], **overrides)
    assert r.status_code == 422
    first = r.json()["detail"][0]
    assert first["loc"][-1] == field and first["msg"] == message
    assert r.json()["message"] and r.json()["description"]
    assert sc.get("/api/sips", headers=users[0]).json() == []


def test_create_missing_fields_and_auth(sc, users):
    r = sc.post("/api/sips", json={}, headers=users[0])
    assert r.status_code == 422
    assert {e["loc"][-1] for e in r.json()["detail"]} == {
        "scheme_code", "platform", "amount", "day_of_month", "start_date",
    }  # fmt: skip
    assert sc.post("/api/sips", json=BODY).status_code == 401
    assert sc.get("/api/sips").status_code == 401


def test_start_date_a_year_ahead_is_allowed(sc, users):
    far = (date.today() + timedelta(days=300)).isoformat()
    assert start(sc, users[0], start_date=far).status_code == 201


# --- list, scoping ------------------------------------------------------------------------


def test_list_orders_active_then_paused_then_cancelled_and_filters(sc, users):
    a = users[0]
    first = start(sc, a).json()
    second = start(sc, a, amount=6000).json()
    third = start(sc, a, scheme_code=102).json()
    sc.post(f"/api/sips/{first['id']}/stop", headers=a)
    sc.post(f"/api/sips/{second['id']}/pause", headers=a)
    listing = sc.get("/api/sips", headers=a).json()
    assert [(s["id"], s["status"]) for s in listing] == [
        (third["id"], "active"), (second["id"], "paused"), (first["id"], "stopped"),
    ]  # fmt: skip
    only = sc.get(f"/api/sips?mutual_fund_id={third['mutual_fund_id']}", headers=a).json()
    assert [s["id"] for s in only] == [third["id"]]
    assert set(listing[0]) == {
        "id", "mutual_fund_id", "scheme_code", "fund_name", "platform", "amount", "day_of_month",
        "start_date", "end_date", "status", "next_date", "skipped_dates", "instalments_added",
        "invested_via_sip",
    }  # fmt: skip
    # Paused and cancelled SIPs have no next date.
    assert listing[1]["next_date"] is None and listing[2]["next_date"] is None


def test_everything_is_scoped_to_the_user(sc, users):
    a, _, b, _ = users
    mine = start(sc, a).json()
    assert sc.get("/api/sips", headers=b).json() == []
    sip_id = mine["id"]
    for method, path in (
        ("put", f"/api/sips/{sip_id}"),
        ("post", f"/api/sips/{sip_id}/pause"),
        ("post", f"/api/sips/{sip_id}/resume"),
        ("post", f"/api/sips/{sip_id}/stop"),
        ("post", f"/api/sips/{sip_id}/skip"),
        ("delete", f"/api/sips/{sip_id}/skip/2026-04-05"),
        ("delete", f"/api/sips/{sip_id}"),
    ):
        kwargs = {"json": {"amount": 500, "day_of_month": 6}} if method == "put" else {}
        r = getattr(sc, method)(path, headers=b, **kwargs)
        assert r.status_code == 404, path
        assert r.json()["message"] == "SIP not found"
    assert sc.get("/api/sips", headers=a).json()[0]["status"] == "active"
    assert sc.get(f"/api/sips?mutual_fund_id={mine['mutual_fund_id']}", headers=b).json() == []


def test_unknown_sip_is_404(sc, users):
    r = sc.post("/api/sips/99999/pause", headers=users[0])
    assert r.status_code == 404
    assert r.json() == {
        "message": "SIP not found",
        "description": "It may have been deleted already.",
        "detail": {"message": "SIP not found", "description": "It may have been deleted already."},
    }


# --- update -------------------------------------------------------------------------------


def test_update_amount_day_and_end_date(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    r = sc.put(
        f"/api/sips/{sip['id']}",
        json={"amount": 7500, "day_of_month": 12, "end_date": "2026-12-12"},
        headers=a,
    )
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["message"] == "SIP updated"
    assert body["description"] == "Fund A - Direct Growth · ₹7,500 on the 12th of every month"
    assert (body["amount"], body["day_of_month"], body["end_date"]) == (7500, 12, "2026-12-12")
    assert body["next_date"] == "2026-03-12"
    # Posted instalments are untouched.
    assert body["instalments_added"] == 3 and body["invested_via_sip"] == 15000


def test_update_changing_the_day_drops_misaligned_skips_and_never_reposts(sc, users, auth_engine):
    a = users[0]
    sip = start(sc, a).json()
    sc.post(f"/api/sips/{sip['id']}/skip", headers=a)  # 5 Apr
    body = sc.put(
        f"/api/sips/{sip['id']}", json={"amount": 5000, "day_of_month": 6}, headers=a
    ).json()
    assert body["skipped_dates"] == [] and body["next_date"] == "2026-04-06"
    # 5 Apr is no longer a due date, so only the 6th is posted when the date comes.
    with sessionmaker(bind=auth_engine)() as s:
        assert sip_service.post_due(s, date(2026, 4, 30), [sip["id"]]) == {sip["id"]: 1}
        dates = [t.txn_date for t in s.scalars(select(MFTransaction).order_by(MFTransaction.txn_date))]
    assert dates == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5), date(2026, 4, 6)]


def test_update_validation_and_states(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    r = sc.put(url, json={"amount": 50, "day_of_month": 5}, headers=a)
    assert r.status_code == 422 and r.json()["detail"][0]["msg"] == "Must be at least ₹100"
    r = sc.put(url, json={"amount": 500, "day_of_month": 30}, headers=a)
    assert r.json()["detail"][0]["msg"] == "Day must be between 1 and 28"
    r = sc.put(url, json={"amount": 500, "day_of_month": 5, "end_date": "2025-12-31"}, headers=a)
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "End date must be on or after the start date"
    sc.post(f"{url}/stop", headers=a)
    r = sc.put(url, json={"amount": 500, "day_of_month": 5}, headers=a)
    assert r.status_code == 409 and r.json()["message"] == "SIP is cancelled"


def test_update_can_clear_the_end_date(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    sc.put(url, json={"amount": 5000, "day_of_month": 5, "end_date": "2026-12-05"}, headers=a)
    body = sc.put(url, json={"amount": 5000, "day_of_month": 5}, headers=a).json()
    assert body["end_date"] is None


# --- pause, resume, stop ------------------------------------------------------------------


def test_pause_resume_stop_flow(sc, users, monkeypatch):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    r = sc.post(f"{url}/resume", headers=a)
    assert r.status_code == 409 and r.json()["message"] == "SIP isn't paused"

    r = sc.post(f"{url}/pause", headers=a)
    assert r.status_code == 200 and r.json()["message"] == "SIP paused"
    assert r.json()["status"] == "paused" and r.json()["next_date"] is None
    assert sc.post(f"{url}/pause", headers=a).status_code == 409

    # Resumed in late April: April's instalment (due 5 Apr) is skipped for good.
    set_today(monkeypatch, date(2026, 4, 20))
    r = sc.post(f"{url}/resume", headers=a)
    assert r.json()["message"] == "SIP resumed"
    assert r.json()["status"] == "active" and r.json()["next_date"] == "2026-05-05"

    r = sc.post(f"{url}/stop", headers=a)
    assert r.json()["message"] == "SIP cancelled" and r.json()["status"] == "stopped"
    assert r.json()["instalments_added"] == 3
    assert sc.post(f"{url}/stop", headers=a).status_code == 409
    assert sc.post(f"{url}/resume", headers=a).status_code == 409
    assert sc.post(f"{url}/pause", headers=a).status_code == 409


def test_paused_months_are_not_added_after_resume(sc, users, monkeypatch, auth_engine):
    a = users[0]
    sip = start(sc, a).json()
    sc.post(f"/api/sips/{sip['id']}/pause", headers=a)
    set_today(monkeypatch, date(2026, 5, 20))
    sc.post(f"/api/sips/{sip['id']}/resume", headers=a)
    set_today(monkeypatch, date(2026, 6, 10))
    with sessionmaker(bind=auth_engine)() as s:
        assert sip_service.post_due(s, date(2026, 6, 10)) == {sip["id"]: 1}
        dates = [t.txn_date for t in s.scalars(select(MFTransaction).order_by(MFTransaction.txn_date))]
    assert dates == [date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5), date(2026, 6, 5)]


# --- skip ---------------------------------------------------------------------------------


def test_skip_next_then_undo(sc, users, auth_engine):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    r = sc.post(f"{url}/skip", headers=a)
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "Instalment skipped"
    assert r.json()["description"] == "Fund A - Direct Growth · 5 Apr 2026"
    assert r.json()["skipped_dates"] == ["2026-04-05"]
    assert r.json()["next_date"] == "2026-04-05"  # still the next date; the UI shows it as skipped
    assert sc.get("/api/sips", headers=a).json()[0]["skipped_dates"] == ["2026-04-05"]

    with sessionmaker(bind=auth_engine)() as s:
        assert sip_service.post_due(s, date(2026, 4, 10)) == {sip["id"]: 0}

    r = sc.delete(f"{url}/skip/2026-04-05", headers=a)
    assert r.status_code == 200 and r.json()["message"] == "Skip removed"
    assert r.json()["skipped_dates"] == []
    with sessionmaker(bind=auth_engine)() as s:
        assert sip_service.post_due(s, date(2026, 4, 10)) == {sip["id"]: 1}


def test_skip_a_chosen_future_date(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    r = sc.post(f"/api/sips/{sip['id']}/skip", json={"due_date": "2026-06-05"}, headers=a)
    assert r.status_code == 200 and r.json()["skipped_dates"] == ["2026-06-05"]
    sc.post(f"/api/sips/{sip['id']}/skip", json={"due_date": "2026-05-05"}, headers=a)
    assert sc.get("/api/sips", headers=a).json()[0]["skipped_dates"] == ["2026-05-05", "2026-06-05"]


@pytest.mark.parametrize("due", ["2026-03-05", "2026-04-06", "2025-12-05", "2026-12-05"])
def test_skip_rejects_dates_that_are_not_upcoming_instalments(sc, users, due):
    a = users[0]
    # Ends in October, so December is past the end; 5 Mar is already added; the 6th is off schedule.
    sip = start(sc, a).json()
    sc.put(
        f"/api/sips/{sip['id']}",
        json={"amount": 5000, "day_of_month": 5, "end_date": "2026-10-05"},
        headers=a,
    )
    r = sc.post(f"/api/sips/{sip['id']}/skip", json={"due_date": due}, headers=a)
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "Pick an upcoming instalment date"
    assert sc.get("/api/sips", headers=a).json()[0]["skipped_dates"] == []


def test_skip_twice_conflicts_and_needs_a_running_sip(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    sc.post(f"{url}/skip", headers=a)
    r = sc.post(f"{url}/skip", json={"due_date": "2026-04-05"}, headers=a)
    assert r.status_code == 409 and r.json()["message"] == "Instalment already skipped"
    sc.post(f"{url}/pause", headers=a)
    r = sc.post(f"{url}/skip", headers=a)
    assert r.status_code == 409 and r.json()["message"] == "SIP isn't running"


def test_skip_with_no_upcoming_instalment(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    sc.put(
        f"/api/sips/{sip['id']}",
        json={"amount": 5000, "day_of_month": 5, "end_date": "2026-03-05"},
        headers=a,
    )
    r = sc.post(f"/api/sips/{sip['id']}/skip", headers=a)
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "There is no upcoming instalment to skip"


def test_unskip_errors(sc, users, auth_engine):
    a = users[0]
    sip = start(sc, a).json()
    url = f"/api/sips/{sip['id']}"
    r = sc.delete(f"{url}/skip/2026-04-05", headers=a)
    assert r.status_code == 404 and r.json()["message"] == "Skip not found"
    assert sc.delete(f"{url}/skip/not-a-date", headers=a).status_code == 422
    # A skip row whose date has passed can't be undone.
    with sessionmaker(bind=auth_engine)() as s:
        s.add(MfSipSkip(sip_id=sip["id"], due_date=date(2026, 2, 5)))
        s.commit()
    r = sc.delete(f"{url}/skip/2026-02-05", headers=a)
    assert r.status_code == 422
    assert r.json()["detail"][0]["msg"] == "Pick an upcoming instalment date"


# --- delete -------------------------------------------------------------------------------


def test_delete_keeps_instalments(sc, users, auth_engine):
    a = users[0]
    sip = start(sc, a).json()
    sc.post(f"/api/sips/{sip['id']}/skip", headers=a)
    r = sc.delete(f"/api/sips/{sip['id']}", headers=a)
    assert r.status_code == 200
    assert r.json() == {
        "message": "SIP deleted",
        "description": "Fund A - Direct Growth · instalments already added stay in your holding",
    }
    assert sc.get("/api/sips", headers=a).json() == []
    page = sc.get(f"/api/holdings/mf/{sip['mutual_fund_id']}/transactions", headers=a).json()
    assert page["total"] == 3 and not any(t["sip"] for t in page["items"])
    holding = sc.get(f"/api/assets/mf/{sip['mutual_fund_id']}", headers=a).json()
    assert holding["invested_amount"] == 15000
    with sessionmaker(bind=auth_engine)() as s:
        assert s.scalars(select(MfSipSkip)).all() == []
        assert s.scalars(select(MfSip)).all() == []
    assert sc.delete(f"/api/sips/{sip['id']}", headers=a).status_code == 404


# --- MF holdings: sip field and transactions ---------------------------------------------


def test_holdings_list_and_detail_carry_the_sip(sc, users):
    a = users[0]
    plain = sc.post("/api/assets/mf", json={**HOLDING, "scheme_code": 102}, headers=a).json()
    sip = start(sc, a).json()
    items = {i["id"]: i for i in sc.get("/api/holdings/mf", headers=a).json()["items"]}
    assert items[plain["id"]]["sip"] is None
    assert items[sip["mutual_fund_id"]]["sip"] == {
        "id": sip["id"], "amount": 5000, "day_of_month": 5, "status": "active",
        "next_date": "2026-04-05",
    }  # fmt: skip
    detail = sc.get(f"/api/holdings/mf/{sip['mutual_fund_id']}", headers=a).json()
    assert detail["item"]["sip"] == items[sip["mutual_fund_id"]]["sip"]
    assert sc.get(f"/api/holdings/mf/{plain['id']}", headers=a).json()["item"]["sip"] is None


def test_holding_sip_shows_paused_and_hides_cancelled(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    hid = sip["mutual_fund_id"]
    sc.post(f"/api/sips/{sip['id']}/pause", headers=a)
    shown = sc.get(f"/api/holdings/mf/{hid}", headers=a).json()["item"]["sip"]
    assert shown["status"] == "paused" and shown["next_date"] is None
    sc.post(f"/api/sips/{sip['id']}/resume", headers=a)
    sc.post(f"/api/sips/{sip['id']}/stop", headers=a)
    assert sc.get(f"/api/holdings/mf/{hid}", headers=a).json()["item"]["sip"] is None


def test_holding_prefers_the_active_sip(sc, users):
    a = users[0]
    first = start(sc, a).json()
    second = start(sc, a, amount=6000, mutual_fund_id=first["mutual_fund_id"]).json()
    sc.post(f"/api/sips/{second['id']}/pause", headers=a)
    shown = sc.get(f"/api/holdings/mf/{first['mutual_fund_id']}", headers=a).json()["item"]["sip"]
    assert shown["id"] == first["id"]


def test_transactions_page_shape_and_nav(sc, users):
    a = users[0]
    sip = start(sc, a).json()
    r = sc.get(f"/api/holdings/mf/{sip['mutual_fund_id']}/transactions", headers=a)
    assert r.status_code == 200
    body = r.json()
    assert (body["total"], body["page"], body["page_size"], body["page_count"]) == (3, 1, 10, 1)
    assert body["items"][0] == {
        "id": body["items"][0]["id"], "date": "2026-03-05", "kind": "purchase", "amount": 5000,
        "units": 99.995, "nav": 50.0, "sip": True,
    }  # fmt: skip
    assert [t["date"] for t in body["items"]] == ["2026-03-05", "2026-02-05", "2026-01-05"]


def test_transactions_paginate_ten_at_a_time(sc, users):
    a = users[0]
    sip = start(sc, a, start_date="2025-01-05").json()  # Jan 2025 to Mar 2026 = 15
    assert sip["instalments_added"] == 15
    url = f"/api/holdings/mf/{sip['mutual_fund_id']}/transactions"
    one = sc.get(url, headers=a).json()
    two = sc.get(f"{url}?page=2", headers=a).json()
    assert (len(one["items"]), len(two["items"])) == (10, 5)
    assert one["total"] == 15 and two["page"] == 2 and two["page_count"] == 2
    assert one["items"][0]["date"] == "2026-03-05" and two["items"][-1]["date"] == "2025-01-05"
    assert sc.get(f"{url}?page=9", headers=a).json()["page"] == 2  # clamped
    assert sc.get(f"{url}?page=0", headers=a).status_code == 422


def test_transactions_are_scoped_and_404(sc, users):
    a, _, b, _ = users
    sip = start(sc, a).json()
    url = f"/api/holdings/mf/{sip['mutual_fund_id']}/transactions"
    assert sc.get(url, headers=b).status_code == 404
    assert sc.get("/api/holdings/mf/99999/transactions", headers=a).status_code == 404
    assert sc.get(url).status_code == 401


def test_transaction_nav_without_units_is_null(sc, users, auth_engine):
    a = users[0]
    held = sc.post("/api/assets/mf", json=HOLDING, headers=a).json()
    with sessionmaker(bind=auth_engine)() as s:
        s.add(
            MFTransaction(
                mutual_fund_id=held["id"], txn_date=date(2025, 6, 1), kind="purchase",
                amount=Decimal("0"), units=Decimal("0"),
            )
        )  # fmt: skip
        s.add(
            MFTransaction(
                mutual_fund_id=held["id"], txn_date=date(2025, 7, 1), kind="redemption",
                amount=Decimal("500"), units=Decimal("10"),
            )
        )  # fmt: skip
        s.commit()
    items = sc.get(f"/api/holdings/mf/{held['id']}/transactions", headers=a).json()["items"]
    assert [(t["kind"], t["nav"], t["sip"]) for t in items] == [
        ("redemption", 50.0, False), ("purchase", None, False),
    ]  # fmt: skip
