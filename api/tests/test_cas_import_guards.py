"""CAS re-import guards: funds with sales recorded here, and SIP instalments newer than the statement."""

from datetime import date
from decimal import Decimal

import casparser
from sqlalchemy.orm import sessionmaker

from app.models import HoldingExit, MfSip, MFTransaction, MutualFund
from app.services.sip import today_ist
from tests.test_cas_import import (  # noqa: F401  (fixtures)
    commit,
    commit_row,
    mf_client,
    scheme,
    statement,
    upload,
)
from tests.test_scoping import client, users  # noqa: F401


def add_fund(client, headers):
    return client.post(
        "/api/assets/mf", headers=headers,
        json=dict(
            scheme_name="Fund A - Direct Growth", scheme_code=100, category="equity", units=10,
            avg_nav=100, invested_amount=1000, purchase_date="2024-01-01",
        ),
    ).json()  # fmt: skip


def user_id_of(engine, holding_id):
    with sessionmaker(bind=engine)() as session:
        return session.get(MutualFund, holding_id).user_id


def record_sale(engine, holding_id):
    with sessionmaker(bind=engine)() as session:
        row = HoldingExit(
            user_id=session.get(MutualFund, holding_id).user_id, asset_type="mf",
            holding_id=holding_id, kind="sale", exit_date=date(2025, 2, 1),
            quantity=Decimal(1), amount=Decimal(100), cost=Decimal(90), destination="none",
        )  # fmt: skip
        session.add(row)
        session.commit()
        return row.id


def delete_exit(engine, exit_id):
    with sessionmaker(bind=engine)() as session:
        session.delete(session.get(HoldingExit, exit_id))
        session.commit()


def test_preview_marks_funds_with_sales(mf_client, users, auth_engine, monkeypatch):  # noqa: F811
    a = users[0]
    mine = add_fund(mf_client, a)
    monkeypatch.setattr(casparser, "read_cas_pdf", lambda *x, **k: statement([("1", [scheme()])]))
    row = upload(mf_client, a).json()["rows"][0]
    assert row["has_sales"] is False and row["existing"][0]["has_sales"] is False
    record_sale(auth_engine, mine["id"])
    row = upload(mf_client, a).json()["rows"][0]
    assert row["has_sales"] is True and row["existing"][0]["has_sales"] is True


def test_update_of_a_fund_with_sales_is_refused_and_saves_nothing(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    mine = add_fund(mf_client, a)
    exit_id = record_sale(auth_engine, mine["id"])
    r = commit(
        mf_client, a,
        [commit_row(), commit_row(action="update", holding_id=mine["id"], units=20, avg_nav=50)],
    )  # fmt: skip
    assert r.status_code == 422
    assert r.json()["message"] == "Couldn't import — nothing was saved"
    assert "Sales are recorded for this fund here" in r.json()["description"]
    items = mf_client.get("/api/assets/mf", headers=a).json()
    assert len(items) == 1 and items[0]["units"] == 10

    added = commit(mf_client, a, [commit_row(action="create")])
    assert added.status_code == 200 and len(mf_client.get("/api/assets/mf", headers=a).json()) == 2

    delete_exit(auth_engine, exit_id)  # sale undone
    ok = commit(mf_client, a, [commit_row(action="update", holding_id=mine["id"], units=20, avg_nav=50)])
    assert ok.status_code == 200, ok.json()
    assert mf_client.get(f"/api/assets/mf/{mine['id']}", headers=a).json()["units"] == 20


def seed_sip_fund(client, headers, engine):
    mine = add_fund(client, headers)
    hid = mine["id"]
    with sessionmaker(bind=engine)() as session:
        session.add(
            MfSip(
                id=1, user_id=session.get(MutualFund, hid).user_id, mutual_fund_id=hid,
                scheme_code=100, platform="x", amount=100, day_of_month=5,
                start_date=date(2025, 1, 1), post_from=date(2025, 1, 1), status="active",
            )
        )  # fmt: skip
        session.flush()
        for day, amount, units, sip in [
            (date(2025, 1, 5), 100, "1.000", 1),
            (date(2025, 4, 5), 100, "2.000", 1),
            (date(2025, 5, 5), 150, "3.000", 1),
            (date(2025, 4, 6), 10, "1.000", None),  # not a SIP row: always replaced
        ]:
            session.add(
                MFTransaction(
                    mutual_fund_id=hid, txn_date=day, kind="purchase", amount=Decimal(amount),
                    units=Decimal(units), sip_id=sip,
                )
            )  # fmt: skip
        session.commit()
    return hid


def txn_dates(engine, holding_id):
    with sessionmaker(bind=engine)() as session:
        rows = session.query(MFTransaction).filter_by(mutual_fund_id=holding_id).all()
        return sorted(t.txn_date for t in rows)


def test_update_keeps_sip_rows_after_the_statement_and_adds_them_to_totals(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    cas_txn = dict(date="2025-02-01", type="purchase", amount=1000, units=100)
    r = mf_client.post(
        "/api/import/cas/commit", headers=a,
        json={
            "statement_to": "2025-03-31",
            "rows": [commit_row(action="update", holding_id=hid, units=100, avg_nav=10,
                                invested_amount=1000, transactions=[cas_txn])],
        },
    )  # fmt: skip
    assert r.status_code == 200, r.json()
    assert txn_dates(auth_engine, hid) == [date(2025, 2, 1), date(2025, 4, 5), date(2025, 5, 5)]
    h = mf_client.get(f"/api/assets/mf/{hid}", headers=a).json()
    assert h["units"] == 105 and h["invested_amount"] == 1250
    assert h["avg_nav"] == round(1250 / 105, 4)


def test_without_a_statement_period_the_latest_cas_transaction_is_the_cutoff(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    cas_txn = dict(date="2025-04-30", type="purchase", amount=1000, units=100)
    r = commit(
        mf_client, a,
        [commit_row(action="update", holding_id=hid, units=100, avg_nav=10,
                    invested_amount=1000, transactions=[cas_txn])],
    )  # fmt: skip
    assert r.status_code == 200, r.json()
    assert txn_dates(auth_engine, hid) == [date(2025, 4, 30), date(2025, 5, 5)]
    h = mf_client.get(f"/api/assets/mf/{hid}", headers=a).json()
    assert h["units"] == 103 and h["invested_amount"] == 1150


def txn_sums(engine, holding_id):
    with sessionmaker(bind=engine)() as session:
        rows = session.query(MFTransaction).filter_by(mutual_fund_id=holding_id).all()
        return sum(t.units for t in rows), sum(t.amount for t in rows)


def commit_with_period(client, headers, statement_to, hid, transactions):
    return client.post(
        "/api/import/cas/commit", headers=headers,
        json={
            "statement_to": statement_to,
            "rows": [commit_row(action="update", holding_id=hid, units=100, avg_nav=10,
                                invested_amount=1000, transactions=transactions)],
        },
    )  # fmt: skip


def test_a_too_early_statement_date_does_not_double_count_sip_rows(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    cas_txn = dict(date="2025-04-30", type="purchase", amount=1000, units=100)
    r = commit_with_period(mf_client, a, "2025-01-31", hid, [cas_txn])
    assert r.status_code == 200, r.json()
    assert txn_dates(auth_engine, hid) == [date(2025, 4, 30), date(2025, 5, 5)]
    h = mf_client.get(f"/api/assets/mf/{hid}", headers=a).json()
    assert h["units"] == 103 and h["invested_amount"] == 1150


def test_a_future_statement_date_is_refused_and_saves_nothing(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    before = txn_dates(auth_engine, hid)
    cas_txn = dict(date="2025-02-01", type="purchase", amount=1000, units=100)
    r = commit_with_period(mf_client, a, "2999-01-01", hid, [cas_txn])
    assert r.status_code == 422
    assert r.json()["message"] == "Couldn't import — nothing was saved"
    assert r.json()["description"] == "The statement date is in the future."
    assert txn_dates(auth_engine, hid) == before
    assert mf_client.get(f"/api/assets/mf/{hid}", headers=a).json()["units"] == 10


def test_a_statement_date_of_today_is_accepted(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    cas_txn = dict(date="2025-02-01", type="purchase", amount=1000, units=100)
    r = commit_with_period(mf_client, a, today_ist().isoformat(), hid, [cas_txn])
    assert r.status_code == 200, r.json()
    assert txn_dates(auth_engine, hid) == [date(2025, 2, 1)]


def test_no_cas_transactions_with_kept_sip_rows_adds_an_opening_row(mf_client, users, auth_engine):  # noqa: F811
    a = users[0]
    hid = seed_sip_fund(mf_client, a, auth_engine)
    r = commit_with_period(mf_client, a, "2025-03-31", hid, [])
    assert r.status_code == 200, r.json()
    h = mf_client.get(f"/api/assets/mf/{hid}", headers=a).json()
    assert h["units"] == 105 and h["invested_amount"] == 1250
    assert txn_dates(auth_engine, hid) == [date(2024, 1, 1), date(2025, 4, 5), date(2025, 5, 5)]
    units, amount = txn_sums(auth_engine, hid)
    assert units == 105 and amount == 1250
