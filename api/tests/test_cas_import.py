from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import casparser
import pytest
from casparser.exceptions import IncorrectPasswordError
from casparser.types import CASData
from sqlalchemy.orm import sessionmaker

from app.models import MFMaster, MutualFund
from app.services import cas_import
from tests.test_scoping import client, users  # noqa: F401

PDF = b"%PDF-1.4 fake"


def txn(day, kind, units, balance, amount="1000"):
    return dict(
        date=day, description="x", amount=amount, units=units, nav="10", balance=balance, type=kind
    )  # fmt: skip


def scheme(
    name="Fund A - Direct Growth", amfi="100", isin="INF000A00001", close="100", cost="1000",
    value="1500", transactions=(), val_date="2025-03-31",
):  # fmt: skip
    return dict(
        scheme=name, rta_code="X", rta="CAMS", isin=isin, amfi=amfi, open="0", close=close,
        close_calculated=close, transactions=list(transactions),
        valuation=dict(date=val_date, nav="15", cost=cost, value=value),
    )  # fmt: skip


def statement(folios):
    return CASData.model_validate(
        dict(
            statement_period={"from": "01-Jan-2025", "to": "31-Mar-2025"},
            folios=[dict(folio=f, amc="Test AMC", schemes=s) for f, s in folios],
            investor_info=dict(name="n", email="e", address="a", mobile="m"),
            cas_type="DETAILED",
            file_type="CAMS",
        )
    )


def master(code=100, name="Fund A - Direct Growth", **kw):
    fields = dict(
        scheme_code=code, name=name, amc="Test AMC Mutual Fund", category="equity",
        plan="direct", option="growth", isin_growth_payout="INF000A00001", isin_reinvest=None,
        amfi_category=None, idcw_frequency=None, is_active=True,
    )  # fmt: skip
    fields.update(kw)
    return SimpleNamespace(**fields)


def rows_of(data, masters=(), existing=None):
    by_code, by_isin = cas_import.master_lookups(masters)
    return cas_import.build_rows(data, by_code, by_isin, existing or {})


# --- pure logic ---------------------------------------------------------------------------


def test_purchase_date_restarts_after_zero_balance():
    s = statement(
        [
            (
                "1",
                [
                    scheme(
                        transactions=[
                            txn("2020-01-10", "PURCHASE", "10", "10"),
                            txn("2021-01-10", "REDEMPTION", "-10", "0"),
                            txn("2022-05-02", "PURCHASE_SIP", "5", "5"),
                            txn("2023-01-02", "PURCHASE", "5", "10"),
                        ]
                    )
                ],
            )
        ]
    ).folios[0].schemes[0]
    assert cas_import.purchase_date_for(s) == date(2022, 5, 2)


def test_purchase_date_summary_uses_valuation_date():
    s = statement([("1", [scheme()])]).folios[0].schemes[0]
    assert cas_import.purchase_date_for(s) == date(2025, 3, 31)


def test_merge_across_folios_matches_by_code_then_isin():
    data = statement(
        [
            ("1", [scheme(close="60", cost="600", value="900", transactions=[txn("2022-02-01", "PURCHASE", "60", "60")])]),
            ("2", [scheme(amfi=None, close="40", cost="400", value="600", transactions=[txn("2021-06-01", "PURCHASE", "40", "40")])]),
        ]
    )  # fmt: skip
    rows, hidden = rows_of(data, [master()])
    assert hidden == 0 and len(rows) == 1
    row = rows[0]
    assert row["key"] == "scheme:100" and row["scheme_code"] == 100
    assert row["units"] == Decimal("100.000") and row["invested_amount"] == Decimal("1000.00")
    assert row["avg_nav"] == Decimal("10.0000") and row["current_value"] == Decimal("1500.00")
    assert row["purchase_date"] == date(2021, 6, 1)
    assert row["folios"] == ["1", "2"] and row["plan"] == "direct" and row["importable"]
    assert row["amc"] == "Test AMC Mutual Fund"


def test_avg_nav_rounding_passes_consistency():
    data = statement([("1", [scheme(close="3", cost="100")])])
    (row,), _ = rows_of(data, [master()])
    assert row["avg_nav"] == Decimal("33.3333") and row["importable"] and row["issue"] is None


def test_unmatched_missing_cost_and_zero_units():
    data = statement(
        [
            (
                "1",
                [
                    scheme(name="Ghost", amfi="999", isin="INF999Z99999"),
                    scheme(name="NoCost", amfi="101", isin="INF000A00002", cost=None),
                    scheme(name="Gone", amfi="102", isin="INF000A00003", close="0.000"),
                ],
            )
        ]
    )
    rows, hidden = rows_of(data, [master(101, "NoCost", isin_growth_payout="INF000A00002")])
    assert hidden == 1
    ghost, nocost = rows
    assert ghost["scheme_code"] is None and ghost["category"] == "other" and not ghost["importable"]
    assert ghost["issue"] == "Not found in the AMFI scheme list"
    assert ghost["key"] == "isin:INF999Z99999" and ghost["plan"] is None
    assert not nocost["importable"] and nocost["issue"]


def test_existing_holdings_attached():
    holding = SimpleNamespace(
        id=5, units=Decimal(1), invested_amount=Decimal(10), avg_nav=Decimal(10),
        purchase_date=date(2024, 1, 1),
    )  # fmt: skip
    (row,), _ = rows_of(statement([("1", [scheme()])]), [master()], {100: [holding]})
    assert row["existing"][0]["id"] == 5


# --- endpoints ----------------------------------------------------------------------------


@pytest.fixture
def mf_client(client, auth_engine):  # noqa: F811
    MFMaster.__table__.create(auth_engine, checkfirst=True)
    with sessionmaker(bind=auth_engine)() as session:
        session.add(
            MFMaster(
                scheme_code=100, name="Fund A - Direct Growth", amc="Test AMC", category="equity",
                plan="direct", option="growth", isin_growth_payout="INF000A00001",
            )
        )  # fmt: skip
        session.commit()
    return client


def upload(client, headers, content=PDF, password="ABCDE1234F"):
    return client.post(
        "/api/import/cas/preview",
        headers=headers,
        files={"file": ("cas.pdf", content, "application/pdf")},
        data={"password": password},
    )


def test_preview_requires_auth(mf_client):
    assert upload(mf_client, {}).status_code == 401


def test_preview_wrong_password(mf_client, users, monkeypatch):  # noqa: F811
    def boom(*a, **k):
        raise IncorrectPasswordError("bad")

    monkeypatch.setattr(casparser, "read_cas_pdf", boom)
    r = upload(mf_client, users[0])
    assert r.status_code == 400
    assert r.json()["message"] == "Wrong password"
    assert r.json()["description"] == "The CAS password is usually your PAN in capitals."


def test_preview_empty_password_needed(mf_client, users, monkeypatch):  # noqa: F811
    def boom(*a, **k):
        raise IncorrectPasswordError("bad")

    monkeypatch.setattr(casparser, "read_cas_pdf", boom)
    r = upload(mf_client, users[0], password="  ")
    assert r.status_code == 400
    assert r.json()["message"] == "Password needed"
    assert r.json()["description"] == (
        "This statement is password-protected. The password is usually your PAN in capitals."
    )


def test_preview_non_pdf_and_too_large(mf_client, users):  # noqa: F811
    r = upload(mf_client, users[0], content=b"hello")
    assert r.status_code == 422 and r.json()["message"] == "Couldn't read this statement"
    big = upload(mf_client, users[0], content=PDF + b"0" * (cas_import.MAX_FILE_BYTES + 1))
    assert big.status_code == 413


def test_preview_depository_and_unreadable(mf_client, users, monkeypatch):  # noqa: F811
    monkeypatch.setattr(casparser, "read_cas_pdf", lambda *a, **k: SimpleNamespace(file_type="NSDL"))
    r = upload(mf_client, users[0])
    assert r.status_code == 422
    assert r.json()["message"] == "Depository statements aren't supported yet"

    def boom(*a, **k):
        raise ValueError("garbage")

    monkeypatch.setattr(casparser, "read_cas_pdf", boom)
    assert upload(mf_client, users[0]).json()["message"] == "Couldn't read this statement"


def test_preview_ok_and_empty(mf_client, users, monkeypatch):  # noqa: F811
    a = users[0]
    mf_client.post(
        "/api/assets/mf", headers=a,
        json=dict(
            scheme_name="Fund A - Direct Growth", scheme_code=100, category="equity", units=10,
            avg_nav=100, invested_amount=1000, purchase_date="2024-01-01",
        ),
    )  # fmt: skip
    data = statement([("1", [scheme(), scheme(name="Zero", amfi="5", isin="Z", close="0")])])
    monkeypatch.setattr(casparser, "read_cas_pdf", lambda *a, **k: data)
    body = upload(mf_client, a).json()
    assert body["hidden_zero"] == 1 and len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["scheme_code"] == 100 and row["importable"] and row["units"] == 100
    assert len(row["existing"]) == 1
    assert upload(mf_client, users[2]).json()["rows"][0]["existing"] == []
    assert body["statement_from"] == "2025-01-01" and body["statement_to"] == "2025-03-31"

    monkeypatch.setattr(casparser, "read_cas_pdf", lambda *a, **k: statement([]))
    empty = upload(mf_client, a)
    assert empty.status_code == 200 and empty.json()["rows"] == []


def commit_row(**kw):
    row = dict(
        action="create", holding_id=None, scheme_code=100, scheme_name="x", category="equity",
        units=100, avg_nav=10, invested_amount=1000, purchase_date="2024-01-01",
    )  # fmt: skip
    row.update(kw)
    return row


def commit(client, headers, rows):
    return client.post("/api/import/cas/commit", headers=headers, json={"rows": rows})


def test_commit_create_and_update_own(mf_client, users):  # noqa: F811
    a = users[0]
    mine = mf_client.post(
        "/api/assets/mf", headers=a,
        json=dict(
            scheme_name="Fund A - Direct Growth", scheme_code=100, category="equity", units=10,
            avg_nav=100, invested_amount=1000, purchase_date="2024-01-01", platform="Zerodha",
            notes="keep",
        ),
    ).json()  # fmt: skip
    r = commit(
        mf_client, a,
        [commit_row(), commit_row(action="update", holding_id=mine["id"], units=20, avg_nav=50)],
    )  # fmt: skip
    assert r.status_code == 200, r.json()
    assert r.json()["message"] == "Imported 2 funds"
    assert r.json()["description"] == "1 added, 1 updated."
    assert (r.json()["created"], r.json()["updated"]) == (1, 1)
    items = mf_client.get("/api/assets/mf", headers=a).json()
    assert len(items) == 2
    updated = next(i for i in items if i["id"] == mine["id"])
    assert updated["units"] == 20 and updated["platform"] == "Zerodha" and updated["notes"] == "keep"
    created = next(i for i in items if i["id"] != mine["id"])
    assert created["platform"] is None and created["scheme_name"] == "Fund A - Direct Growth"


def test_commit_rejects_other_users_holding(mf_client, users):  # noqa: F811
    a, _, b, _ = users
    theirs = mf_client.post(
        "/api/assets/mf", headers=b,
        json=dict(
            scheme_name="B Fund", category="equity", units=10, avg_nav=100, invested_amount=1000,
            purchase_date="2024-01-01",
        ),
    ).json()  # fmt: skip
    r = commit(mf_client, a, [commit_row(action="update", holding_id=theirs["id"])])
    assert r.status_code == 422 and r.json()["message"] and r.json()["description"]
    still = mf_client.get(f"/api/assets/mf/{theirs['id']}", headers=b).json()
    assert still["units"] == 10


def test_commit_invalid_row_rolls_back_everything(mf_client, users):  # noqa: F811
    a = users[0]
    r = commit(mf_client, a, [commit_row(), commit_row(scheme_name="Bad Fund", invested_amount=5)])
    assert r.status_code == 422
    assert "Bad Fund" in r.json()["description"]
    assert mf_client.get("/api/assets/mf", headers=a).json() == []
    unknown = commit(mf_client, a, [commit_row(), commit_row(scheme_code=777)])
    assert unknown.status_code == 422
    assert mf_client.get("/api/assets/mf", headers=a).json() == []
