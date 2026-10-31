from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models import MFTransaction, MutualFund
from app.schemas.cas_import import CasTransaction
from app.services import cas_import
from app.services.valuation import mf_xirr, xirr
from tests.test_cas_import import (  # noqa: F401
    commit,
    commit_row,
    mf_client,
    rows_of,
    scheme,
    statement,
    txn,
)
from tests.test_cas_import import master as cas_master
from tests.test_scoping import client, users  # noqa: F401

D = Decimal


def t(day, kind, amount, units):
    return SimpleNamespace(txn_date=day, kind=kind, amount=D(amount), units=D(units))


# --- solver -------------------------------------------------------------------------------


def test_xirr_single_year_ten_percent():
    rate = xirr([(date(2025, 1, 1), D(-10000)), (date(2026, 1, 1), D(11000))])
    assert round(float(rate) * 100, 2) == 10.00


def test_xirr_multi_flow_npv_is_zero():
    flows = [
        (date(2024, 1, 1), D(-10000)),
        (date(2024, 7, 1), D(-5000)),
        (date(2025, 3, 1), D(2000)),
        (date(2026, 1, 1), D(16000)),
    ]
    rate = float(xirr(flows))
    start = flows[0][0]
    npv = sum(float(a) / (1 + rate) ** ((d - start).days / 365) for d, a in flows)
    assert abs(npv) < 1e-4


def test_xirr_negative_return():
    rate = xirr([(date(2025, 1, 1), D(-10000)), (date(2026, 1, 1), D(9000))])
    assert round(float(rate) * 100, 2) == -10.00


def test_xirr_none_cases():
    d = date(2025, 1, 1)
    assert xirr([]) is None
    assert xirr([(d, D(-100))]) is None
    assert xirr([(d, D(-100)), (d + timedelta(days=30), D(-50))]) is None  # no sign change
    assert xirr([(d, D(-100)), (d, D(120))]) is None  # one date


# --- basis selection ----------------------------------------------------------------------


AS_OF = date(2026, 1, 1)


def test_basis_transactions_when_units_match():
    txns = [t(date(2025, 1, 1), "purchase", "10000", "100")]
    pct, basis, count = mf_xirr(D(100), D(10000), date(2025, 1, 1), D(11000), txns, AS_OF)
    assert (pct, basis, count) == (D("10.00"), "transactions", 1)


def test_basis_counts_redemptions():
    txns = [
        t(date(2025, 1, 1), "purchase", "10000", "100"),
        t(date(2025, 6, 1), "redemption", "6000", "50"),
    ]
    pct, basis, count = mf_xirr(D(50), D(5000), date(2025, 1, 1), D(6000), txns, AS_OF)
    assert basis == "transactions" and count == 2 and pct is not None


def test_basis_purchase_date_when_units_mismatch_or_none():
    txns = [t(date(2025, 1, 1), "purchase", "10000", "100")]
    mismatch = mf_xirr(D(120), D(10000), date(2025, 1, 1), D(11000), txns, AS_OF)
    assert mismatch == (D("10.00"), "purchase_date", 0)
    none = mf_xirr(D(100), D(10000), date(2025, 1, 1), D(11000), [], AS_OF)
    assert none == (D("10.00"), "purchase_date", 0)


def test_mf_xirr_none_when_unsolvable():
    assert mf_xirr(D(100), D(10000), AS_OF, D(11000), [], AS_OF) == (None, None, 0)


def test_mf_xirr_accepts_iso_string_dates():
    # nav_date can arrive as an ISO string from the item builder; must match the date result.
    txns = [
        t(date(2025, 1, 1), "purchase", "10000", "100"),
        t(date(2025, 6, 1), "redemption", "6000", "50"),
    ]
    as_dates = mf_xirr(D(50), D(5000), date(2025, 1, 1), D(6000), txns, AS_OF)
    as_strings = mf_xirr(D(50), D(5000), "2025-01-01", D(6000), txns, "2026-01-01")
    assert as_strings == as_dates and as_dates[0] is not None

    no_txns_dates = mf_xirr(D(100), D(10000), date(2025, 1, 1), D(11000), [], AS_OF)
    no_txns_strings = mf_xirr(D(100), D(10000), "2025-01-01", D(11000), [], "2026-01-01")
    assert no_txns_strings == no_txns_dates == (D("10.00"), "purchase_date", 0)


# --- preview rows -------------------------------------------------------------------------


def test_preview_transactions_merged_sorted_and_filtered():
    folio1 = scheme(
        transactions=[
            txn("2024-03-01", "PURCHASE_SIP", "5", "5", amount="500"),
            txn("2024-01-10", "PURCHASE", "10", "10", amount="1000"),
            txn("2024-01-10", "STAMP_DUTY_TAX", None, "10", amount="0.05"),
            txn("2024-02-01", "DIVIDEND_PAYOUT", None, "10", amount="20"),
            txn("2024-02-02", "MISC", "0", "10", amount="30"),
        ]
    )
    folio2 = scheme(
        transactions=[
            txn("2024-02-15", "SWITCH_OUT", "-3", "7", amount="330"),
            txn("2024-01-20", "SWITCH_IN", "4", "4", amount="400"),
        ]
    )
    (row,), _ = rows_of(statement([("1", [folio1]), ("2", [folio2])]), [cas_master()])
    got = [(str(x["date"]), x["type"], x["amount"], x["units"]) for x in row["transactions"]]
    assert got == [
        ("2024-01-10", "purchase", D("1000.00"), D("10.000")),
        ("2024-01-20", "purchase", D("400.00"), D("4.000")),
        ("2024-02-15", "redemption", D("330.00"), D("3.000")),
        ("2024-03-01", "purchase", D("500.00"), D("5.000")),
    ]


# --- commit -------------------------------------------------------------------------------

TXNS = [
    {"date": "2024-01-01", "type": "purchase", "amount": 1000, "units": 100},
    {"date": "2024-06-01", "type": "redemption", "amount": 200, "units": 20},
]


def stored(auth_engine, holding_id):
    with sessionmaker(bind=auth_engine)() as s:
        rows = s.scalars(
            select(MFTransaction)
            .where(MFTransaction.mutual_fund_id == holding_id)
            .order_by(MFTransaction.txn_date)
        ).all()
        return [(r.txn_date, r.kind, r.amount, r.units) for r in rows]


@pytest.fixture
def txn_client(mf_client, auth_engine):  # noqa: F811
    MFTransaction.__table__.create(auth_engine, checkfirst=True)
    return mf_client


def holding_ids(auth_engine):
    with sessionmaker(bind=auth_engine)() as s:
        return list(s.scalars(select(MutualFund.id).order_by(MutualFund.id)))


def test_commit_create_saves_and_update_replaces(txn_client, users, auth_engine):  # noqa: F811
    a = users[0]
    r = commit(txn_client, a, [commit_row(transactions=TXNS)])
    assert r.status_code == 200, r.json()
    (hid,) = holding_ids(auth_engine)
    assert stored(auth_engine, hid) == [
        (date(2024, 1, 1), "purchase", D("1000.00"), D("100.000")),
        (date(2024, 6, 1), "redemption", D("200.00"), D("20.000")),
    ]

    new = [{"date": "2024-02-01", "type": "purchase", "amount": 50, "units": 5}]
    r = commit(txn_client, a, [commit_row(action="update", holding_id=hid, transactions=new)])
    assert r.status_code == 200, r.json()
    assert stored(auth_engine, hid) == [(date(2024, 2, 1), "purchase", D("50.00"), D("5.000"))]

    r = commit(txn_client, a, [commit_row(action="update", holding_id=hid, transactions=[])])
    assert r.status_code == 200, r.json()
    assert stored(auth_engine, hid) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"date": "2999-01-01", "type": "purchase", "amount": 10, "units": 1},
        {"date": "2024-01-01", "type": "purchase", "amount": 0, "units": 1},
        {"date": "2024-01-01", "type": "purchase", "amount": 10, "units": -1},
    ],
)
def test_commit_rejects_bad_transactions(txn_client, users, auth_engine, bad):  # noqa: F811
    a = users[0]
    r = commit(txn_client, a, [commit_row(scheme_name="Bad Txn"), commit_row(transactions=[bad])])
    assert r.status_code == 422
    assert r.json()["message"] and "x" in r.json()["description"]
    assert holding_ids(auth_engine) == []


def test_transaction_error_limit():
    ok = CasTransaction(date=date(2024, 1, 1), type="purchase", amount=D(1), units=D(1))
    assert cas_import.transaction_error([ok] * cas_import.MAX_TRANSACTIONS) is None
    assert cas_import.transaction_error([ok] * (cas_import.MAX_TRANSACTIONS + 1))
