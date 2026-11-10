"""The `attention` block of GET /api/dashboard: maturities in the next 30 days, stale hand-entered
values, SIPs due in the next 7 days (SQLite). Holdings dates are relative to the real today; SIP
dates run on a patched IST today of 2026-03-10."""

from datetime import date, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.models import MFMaster, MfSip, MfSipSkip
from app.services import sip as sip_service
from tests.test_exits_api import BOND, CASH, FD, OTHER, add
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date.today()
SIP_TODAY = date(2026, 3, 10)


def days(n):
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture
def env(client, users, auth_engine, monkeypatch):  # noqa: F811
    MFMaster.__table__.create(auth_engine, checkfirst=True)
    with sessionmaker(bind=auth_engine)() as s:
        s.add(MFMaster(scheme_code=100, name="Fund A - Direct Growth", category="equity", is_active=True))
        s.commit()
    monkeypatch.setattr(sip_service, "today_ist", lambda: SIP_TODAY)
    return client


def bond(c, headers, name, maturity_in, **overrides):
    body = {
        **BOND, "name": name, "isin": None, "purchase_date": days(-400),
        "maturity_date": days(maturity_in), **overrides,
    }  # fmt: skip
    return add(c, headers, "bond", body)


def attention(c, headers):
    r = c.get("/api/dashboard", headers=headers)
    assert r.status_code == 200, r.json()
    return r.json()["attention"]


def sip(auth_engine, user_id, day, status="active", skips=(), **overrides):
    with sessionmaker(bind=auth_engine)() as s:
        row = MfSip(
            user_id=user_id, scheme_code=100, platform="Groww", amount=5000, day_of_month=day,
            start_date=date(2026, 1, 1), post_from=date(2026, 1, 1), status=status, **overrides,
        )  # fmt: skip
        s.add(row)
        s.flush()
        for due in skips:
            s.add(MfSipSkip(sip_id=row.id, due_date=due))
        s.commit()
        return row.id


def test_empty_portfolio_has_empty_attention(env, users):
    a = users[0]
    assert attention(env, a) == {
        "maturing": [], "stale": [], "sips": [],
        "counts": {"maturing": 0, "stale": 0, "sips": 0},
    }  # fmt: skip


def test_maturity_window_boundaries(env, users):
    a = users[0]
    ids = {n: bond(env, a, f"Bond day {n}", n) for n in (0, 1, 30, 31)}
    got = attention(env, a)["maturing"]
    assert [r["id"] for r in got] == [ids[1], ids[30]]
    assert [r["days_left"] for r in got] == [1, 30]
    first = got[0]
    assert first["type"] == "bond" and first["name"] == "Bond day 1"
    assert first["date"] == days(1)
    assert first["amount"] == 10000 and first["approximate"] is False
    assert first["rate"] == 8
    assert attention(env, a)["counts"]["maturing"] == 2


def test_matured_holdings_are_not_listed(env, users):
    a = users[0]
    add(env, a, "fd", {**FD, "start_date": days(-800), "tenure_years": 1})
    bond(env, a, "Past bond", -5, purchase_date=days(-400))
    assert attention(env, a)["maturing"] == []


def test_fd_in_the_window_is_listed_with_its_maturity_value(env, users):
    a = users[0]
    start = TODAY + timedelta(days=12) - relativedelta(months=6)
    fd_id = add(env, a, "fd", {**FD, "start_date": start.isoformat(), "tenure_years": 0, "tenure_months": 6})
    row = attention(env, a)["maturing"][0]
    assert (row["type"], row["id"], row["days_left"]) == ("fd", fd_id, 12)
    assert row["amount"] > 100000 and row["approximate"] is False


def test_sgb_amount_is_present(env, users):
    a = users[0]
    sgb = bond(env, a, "SGB 2032", 20, bond_type="sgb", face_value=None)
    row = attention(env, a)["maturing"][0]
    assert row["id"] == sgb and row["approximate"] is True
    assert row["amount"] is not None and row["amount"] > 0


def test_maturing_rows_sort_by_date_then_type_then_id(env, users):
    a = users[0]
    late = bond(env, a, "Late", 25)
    early = bond(env, a, "Early", 5)
    same = bond(env, a, "Same day", 5)
    got = attention(env, a)["maturing"]
    assert [r["id"] for r in got] == [early, same, late]


def test_stale_boundary_and_order(env, users):
    a = users[0]
    exactly = TODAY - relativedelta(months=6)
    old = exactly - timedelta(days=1)
    older = exactly - timedelta(days=40)
    add(env, a, "cash", {**CASH, "name": "Exactly six", "balance_date": exactly.isoformat()})
    new = add(env, a, "cash", {**CASH, "name": "Just stale", "balance_date": old.isoformat()})
    oldest = add(env, a, "other", {**OTHER, "name": "Oldest", "value_date": older.isoformat()})
    got = attention(env, a)
    assert [(r["type"], r["id"], r["as_of"]) for r in got["stale"]] == [
        ("other", oldest, older.isoformat()), ("cash", new, old.isoformat()),
    ]  # fmt: skip
    assert got["counts"]["stale"] == 2


def test_sips_due_within_seven_days(env, users, auth_engine):
    a, a_id = users[0], users[1]
    in7 = sip(auth_engine, a_id, 17)
    sip(auth_engine, a_id, 18)  # due in 8 days
    today_id = sip(auth_engine, a_id, 10)  # due today
    got = attention(env, a)
    assert [r["id"] for r in got["sips"]] == [today_id, in7]
    assert got["sips"][1] == {
        "id": in7, "fund_name": "Fund A - Direct Growth", "mutual_fund_id": None,
        "amount": 5000, "next_date": "2026-03-17",
    }  # fmt: skip
    assert got["counts"]["sips"] == 2


def test_paused_stopped_and_skipped_sips_are_excluded(env, users, auth_engine):
    a, a_id = users[0], users[1]
    sip(auth_engine, a_id, 12, status="paused")
    sip(auth_engine, a_id, 13, status="stopped")
    sip(auth_engine, a_id, 14, skips=[date(2026, 3, 14)])
    kept = sip(auth_engine, a_id, 15, skips=[date(2026, 4, 15)])
    got = attention(env, a)
    assert [r["id"] for r in got["sips"]] == [kept]


def test_other_users_rows_are_not_shown(env, users, auth_engine):
    a, a_id, b, b_id = users
    bond(env, b, "B bond", 10)
    add(env, b, "cash", {**CASH, "balance_date": "2020-01-01"})
    sip(auth_engine, b_id, 15)
    assert attention(env, a)["counts"] == {"maturing": 0, "stale": 0, "sips": 0}
    assert attention(env, b)["counts"] == {"maturing": 1, "stale": 1, "sips": 1}


def test_lists_are_capped_at_20_with_true_counts(env, users, auth_engine):
    a, a_id = users[0], users[1]
    for n in range(22):
        bond(env, a, f"Bond {n}", 1 + n % 25)
        add(env, a, "cash", {**CASH, "name": f"Account {n}", "balance_date": f"2019-01-{n + 1:02d}"})
    for n in range(22):
        sip(auth_engine, a_id, 11 + n % 7)
    got = attention(env, a)
    assert (len(got["maturing"]), len(got["stale"]), len(got["sips"])) == (20, 20, 20)
    assert got["counts"] == {"maturing": 22, "stale": 22, "sips": 22}
    assert [r["as_of"] for r in got["stale"]] == sorted(r["as_of"] for r in got["stale"])


def test_the_dashboard_adds_at_most_two_queries(env, users, auth_engine):
    a, a_id = users[0], users[1]
    bond(env, a, "Bond", 10)
    sip(auth_engine, a_id, 15)
    statements = []

    def record(conn, cursor, statement, *rest):
        statements.append(statement)

    event.listen(auth_engine, "before_cursor_execute", record)
    try:
        assert env.get("/api/dashboard", headers=a).status_code == 200
    finally:
        event.remove(auth_engine, "before_cursor_execute", record)
    sip_queries = [s for s in statements if "mf_sips" in s]
    name_queries = [s for s in statements if "mf_master" in s]
    assert len(sip_queries) == 1 and len(name_queries) == 1
    assert not any("bond_master" in s for s in statements)

