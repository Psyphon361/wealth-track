"""CHECK constraints and the one-active-funding index on real Postgres (mirrors test_db_constraints).

The SQLite test proves the model declarations; this proves the migrated Postgres schema (0032)
refuses the same rows, by constraint name (`diag.constraint_name`), and that the valid rows pass.
"""

from datetime import datetime, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Cash, HoldingFunding, MFMaster, MFTransaction, MutualFund, NpsMaster
from tests.pg.conftest import make_user_token
from tests.test_db_constraints import BASE, BOUNDARY_OK, MODELS, VIOLATIONS

pytestmark = pytest.mark.pg


@pytest.fixture
def seeded(pg_app):
    """A user, two cash accounts, a fund and an NPS scheme; yields (session factory, base rows)."""
    factory = pg_app.session
    with factory() as session:
        user, _headers = make_user_token(session)
        session.add(
            NpsMaster(
                scheme_id="SM1", pfm_code="PFM1", pfm_name="Pfm", scheme_name="Scheme E",
                tier="I", asset_class="E",
            )
        )
        session.add(MFMaster(scheme_code=1, name="Scheme One", category="equity"))
        cash = [Cash(**{**BASE[Cash], "user_id": user.id, "name": f"C{i}"}) for i in (1, 2)]
        fund = MutualFund(**{**BASE[MutualFund], "user_id": user.id})
        session.add_all([*cash, fund])
        session.commit()
        ids = {"user": user.id, "cash": [c.id for c in cash], "fund": fund.id}
    base = {model: dict(values) for model, values in BASE.items()}
    for values in base.values():
        if "user_id" in values:
            values["user_id"] = ids["user"]
    base[HoldingFunding]["cash_holding_id"] = ids["cash"][0]
    base[MFTransaction]["mutual_fund_id"] = ids["fund"]
    # Fresh scheme per use: Nps rows only reference the master, so SM1 is fine for every insert.
    return factory, base, ids


def attempt(factory, model, values):
    """Insert one row; return the violated constraint name, or None when it was accepted."""
    with factory() as session:
        session.add(model(**values))
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            return error.orig.diag.constraint_name
    return None


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_valid_base_row_is_accepted(seeded, model):
    factory, base, _ids = seeded
    assert attempt(factory, model, base[model]) is None


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_every_violation_is_refused_by_name(seeded, model):
    factory, base, _ids = seeded
    cases = [(name, changes) for name, m, changes in VIOLATIONS if m is model]
    assert cases, f"no violation case for {model.__name__}"
    for name, changes in cases:
        assert attempt(factory, model, {**base[model], **changes}) == name, (name, changes)
    # The refusals left nothing behind: a valid row still goes in.
    assert attempt(factory, model, base[model]) is None


@pytest.mark.parametrize(
    ("model", "changes"), BOUNDARY_OK, ids=[f"{m.__name__}-{i}" for i, (m, _) in enumerate(BOUNDARY_OK)]
)
def test_boundary_values_are_accepted(seeded, model, changes):
    factory, base, _ids = seeded
    assert attempt(factory, model, {**base[model], **changes}) is None


def test_checks_survive_a_core_update_of_a_valid_row(seeded):
    """CHECKs also guard UPDATEs, not only inserts."""
    factory, base, ids = seeded
    with factory() as session:
        row = Cash(**{**base[Cash], "name": "Update probe"})
        session.add(row)
        session.commit()
        row.balance = D("-1")
        with pytest.raises(IntegrityError) as caught:
            session.commit()
        session.rollback()
    assert caught.value.orig.diag.constraint_name == "ck_cash_holdings_balance_nonnegative"


# --- one active funding per holding (partial unique index) ---------------------------------


def test_second_active_funding_for_a_holding_is_refused(seeded):
    factory, base, ids = seeded
    assert attempt(factory, HoldingFunding, base[HoldingFunding]) is None
    other = {**base[HoldingFunding], "cash_holding_id": ids["cash"][1]}
    assert attempt(factory, HoldingFunding, other) == "uq_holding_fundings_active"


def test_refunded_funding_does_not_block_a_new_one(seeded):
    factory, base, _ids = seeded
    stamp = datetime(2026, 1, 2, tzinfo=timezone.utc)
    refunded = {**base[HoldingFunding], "refunded_at": stamp}
    assert attempt(factory, HoldingFunding, refunded) is None
    assert attempt(factory, HoldingFunding, base[HoldingFunding]) is None  # funded again
    assert attempt(factory, HoldingFunding, {**refunded, "refunded_at": stamp.replace(day=3)}) is None
    # ...but now that an active one exists, a second active one is refused again.
    assert attempt(factory, HoldingFunding, base[HoldingFunding]) == "uq_holding_fundings_active"


def test_different_holding_or_type_can_be_funded(seeded):
    factory, base, _ids = seeded
    funding = base[HoldingFunding]
    assert attempt(factory, HoldingFunding, funding) is None
    assert attempt(factory, HoldingFunding, {**funding, "holding_id": 2}) is None
    assert attempt(factory, HoldingFunding, {**funding, "asset_type": "mf"}) is None
