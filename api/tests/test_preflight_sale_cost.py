"""scripts/preflight_sale_cost.py: funds whose invested amount drifted from the FIFO cost (SQLite)."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import MFTransaction, MfSip, MutualFund, User

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from preflight_sale_cost import find_gaps, report  # noqa: E402


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine, tables=[m.__table__ for m in (User, MutualFund, MfSip, MFTransaction)]
    )
    with Session(engine) as s:
        s.add(User(id=1, email="a@example.com", password_hash="x"))
        s.commit()
        yield s


def fund(session, invested, *, units="100", closed_on=None, txns=((date(2025, 1, 1), "purchase", 4000, 100),)):
    f = MutualFund(
        user_id=1, scheme_name="Fund A - Direct Growth", category="equity", units=Decimal(units),
        avg_nav=Decimal("40"), invested_amount=Decimal(str(invested)), purchase_date=date(2025, 1, 1),
        closed_on=closed_on,
    )  # fmt: skip
    session.add(f)
    session.flush()
    for d, kind, amount, u in txns:
        session.add(MFTransaction(mutual_fund_id=f.id, txn_date=d, kind=kind, amount=amount, units=u))
    session.commit()
    return f.id


def test_consistent_fund_is_not_listed(session):
    fund(session, 4000)
    gaps, totals = find_gaps(session)
    assert gaps == []
    assert totals == {"with_transactions": 1, "units_match": 1, "gaps": 0, "skipped": 0}
    assert report(gaps, totals) == 0


def test_edited_fund_is_listed(session):
    fid = fund(session, 4050)
    gaps, totals = find_gaps(session)
    assert [g["fund_id"] for g in gaps] == [fid]
    assert gaps[0]["user_id"] == 1
    assert gaps[0]["fifo_cost"] == Decimal("4000.00")
    assert gaps[0]["difference"] == Decimal("50")
    assert totals["gaps"] == 1
    assert report(gaps, totals) == 1


def test_fund_within_one_rupee_is_not_listed(session):
    fund(session, "4000.90")
    gaps, _ = find_gaps(session)
    assert gaps == []


def test_closed_fund_and_fund_without_transactions_are_skipped(session):
    fund(session, 4050, closed_on=date(2025, 6, 1))
    fund(session, 4050, txns=())
    gaps, totals = find_gaps(session)
    assert gaps == []
    assert totals["with_transactions"] == 0


def test_fund_with_mismatching_units_is_skipped(session):
    fund(session, 4050, units="90")
    gaps, totals = find_gaps(session)
    assert gaps == []
    assert totals["with_transactions"] == 1
    assert totals["units_match"] == 0


def test_partly_redeemed_fund_uses_fifo_of_units_left(session):
    txns = (
        (date(2025, 1, 1), "purchase", 4000, 100),
        (date(2025, 2, 1), "purchase", 6000, 100),
        (date(2025, 3, 1), "redemption", 2500, 50),
    )
    fund(session, 8000, units="150", txns=txns)  # FIFO left: 50 x 40 + 100 x 60 = 8,000
    gaps, totals = find_gaps(session)
    assert gaps == []
    assert totals["units_match"] == 1
