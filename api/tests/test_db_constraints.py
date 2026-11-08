"""Database-level invariants: CHECK constraints and the one-active-funding index on the models.

Each case inserts a valid row, then a row that breaks exactly one rule, and expects the database to
refuse it by the constraint's name. SQLite stands in for Postgres (same comparisons).
"""

from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    HoldingExit,
    HoldingFunding,
    MFTransaction,
    MfSip,
    MutualFund,
    Nps,
    Other,
    Pf,
    RecurringDeposit,
    Stock,
)

MODELS = (
    FixedDeposit, RecurringDeposit, Stock, Bond, MutualFund, Nps, Gold, Cash, Pf, Other,
    HoldingExit, HoldingFunding, MfSip, MFTransaction,
)  # fmt: skip
HOLDING_MODELS = (
    FixedDeposit, RecurringDeposit, Stock, Bond, MutualFund, Nps, Gold, Cash, Pf, Other,
)  # fmt: skip

D1 = date(2025, 1, 1)
D2 = date(2026, 1, 1)

# Valid rows, one per model.
BASE = {
    FixedDeposit: dict(
        user_id=1, bank="B", principal=D("1000"), rate=D("7"), start_date=D1, tenure_years=1,
        compounding="quarterly", payout_type="cumulative",
    ),
    RecurringDeposit: dict(
        user_id=1, bank="B", monthly_instalment=D("500"), rate=D("7"), start_date=D1,
        tenure_months=12, compounding="quarterly",
    ),
    Stock: dict(
        user_id=1, name="S", exchange="NSE", quantity=10, avg_buy_price=D("100"), buy_date=D1,
    ),
    Bond: dict(
        user_id=1, name="Bd", issuer="I", bond_type="corporate", quantity=10,
        face_value=D("1000"), purchase_price=D("990"), invested_amount=D("9900"),
        purchase_date=D1, ytm=D("8"), maturity_date=D2,
    ),
    MutualFund: dict(
        user_id=1, scheme_name="F", category="equity", units=D("10"), avg_nav=D("50"),
        invested_amount=D("500"), purchase_date=D1,
    ),
    Nps: dict(user_id=1, scheme_id="SM1", units=D("10"), contributed=D("500"), start_date=D1),
    Gold: dict(
        user_id=1, name="G", form="coin", metal="gold", purity="999", weight_grams=D("5"),
        purchase_date=D1, invested_amount=D("30000"),
    ),
    Cash: dict(
        user_id=1, name="C", kind="savings", balance=D("100"), interest_rate=D("3"),
        balance_date=D1,
    ),
    Pf: dict(
        user_id=1, name="P", kind="epf", balance=D("100"), balance_date=D1,
        interest_rate=D("8"), contributed=D("50"),
    ),
    Other: dict(
        user_id=1, name="O", category="Art", current_value=D("100"), value_date=D2,
        invested_amount=D("80"), acquired_on=D1,
    ),
    HoldingExit: dict(
        user_id=1, asset_type="stock", holding_id=1, kind="sale", exit_date=D2,
        quantity=D("1"), amount=D("100"), cost=D("90"), charges=D("1"), destination="none",
    ),
    HoldingFunding: dict(
        user_id=1, asset_type="stock", holding_id=1, cash_holding_id=1, amount=D("100"),
        funded_on=D1, prev_balance_date=D1,
    ),
    MfSip: dict(
        user_id=1, scheme_code=1, platform="P", amount=D("500"), day_of_month=5,
        start_date=D1, post_from=D1, status="active",
    ),
    MFTransaction: dict(
        mutual_fund_id=1, txn_date=D1, kind="purchase", amount=D("500"), units=D("10"),
    ),
}  # fmt: skip

# (constraint name, model, column changes that break it)
VIOLATIONS = [
    ("ck_fixed_deposits_principal_positive", FixedDeposit, dict(principal=D("0"))),
    ("ck_fixed_deposits_rate_range", FixedDeposit, dict(rate=D("-1"))),
    ("ck_fixed_deposits_rate_range", FixedDeposit, dict(rate=D("100.5"))),
    ("ck_fixed_deposits_tenure_positive", FixedDeposit, dict(tenure_years=0)),
    ("ck_recurring_deposits_instalment_positive", RecurringDeposit, dict(monthly_instalment=0)),
    ("ck_recurring_deposits_rate_range", RecurringDeposit, dict(rate=D("-0.5"))),
    ("ck_recurring_deposits_rate_range", RecurringDeposit, dict(rate=D("101"))),
    ("ck_recurring_deposits_tenure_positive", RecurringDeposit, dict(tenure_months=0)),
    ("ck_stocks_quantity_positive", Stock, dict(quantity=0)),
    ("ck_stocks_avg_buy_price_positive", Stock, dict(avg_buy_price=D("0"))),
    ("ck_bonds_quantity_positive", Bond, dict(quantity=0)),
    ("ck_bonds_purchase_price_positive", Bond, dict(purchase_price=D("0"))),
    ("ck_bonds_invested_nonnegative", Bond, dict(invested_amount=D("-1"))),
    ("ck_bonds_face_value_positive", Bond, dict(face_value=D("0"))),
    ("ck_bonds_maturity_after_purchase", Bond, dict(maturity_date=D1)),
    ("ck_mutual_funds_units_positive", MutualFund, dict(units=D("0"))),
    ("ck_mutual_funds_avg_nav_nonnegative", MutualFund, dict(avg_nav=D("-1"))),
    ("ck_mutual_funds_invested_nonnegative", MutualFund, dict(invested_amount=D("-1"))),
    ("ck_nps_holdings_units_positive", Nps, dict(units=D("0"))),
    ("ck_nps_holdings_contributed_nonnegative", Nps, dict(contributed=D("-1"))),
    ("ck_gold_holdings_weight_positive", Gold, dict(weight_grams=D("0"))),
    ("ck_gold_holdings_invested_nonnegative", Gold, dict(invested_amount=D("-1"))),
    ("ck_cash_holdings_balance_nonnegative", Cash, dict(balance=D("-0.01"))),
    ("ck_cash_holdings_rate_range", Cash, dict(interest_rate=D("-1"))),
    ("ck_cash_holdings_rate_range", Cash, dict(interest_rate=D("100.1"))),
    ("ck_pf_holdings_balance_nonnegative", Pf, dict(balance=D("-1"))),
    ("ck_pf_holdings_rate_range", Pf, dict(interest_rate=D("-1"))),
    ("ck_pf_holdings_rate_range", Pf, dict(interest_rate=D("100.1"))),
    ("ck_pf_holdings_contributed_nonnegative", Pf, dict(contributed=D("-1"))),
    ("ck_other_holdings_value_nonnegative", Other, dict(current_value=D("-1"))),
    ("ck_other_holdings_invested_nonnegative", Other, dict(invested_amount=D("-1"))),
    ("ck_other_holdings_acquired_before_value", Other, dict(acquired_on=date(2026, 6, 1))),
    ("ck_holding_exits_quantity_positive", HoldingExit, dict(quantity=D("0"))),
    ("ck_holding_exits_amount_nonnegative", HoldingExit, dict(amount=D("-1"))),
    ("ck_holding_exits_cost_nonnegative", HoldingExit, dict(cost=D("-1"))),
    ("ck_holding_exits_charges_nonnegative", HoldingExit, dict(charges=D("-1"))),
    ("ck_holding_fundings_amount_positive", HoldingFunding, dict(amount=D("0"))),
    ("ck_mf_sips_amount_positive", MfSip, dict(amount=D("0"))),
    ("ck_mf_sips_end_after_start", MfSip, dict(end_date=date(2024, 12, 31))),
    ("ck_mf_transactions_amount_positive", MFTransaction, dict(amount=D("0"))),
    ("ck_mf_transactions_units_positive", MFTransaction, dict(units=D("0"))),
]

# Values that sit exactly on a boundary and must still be accepted.
BOUNDARY_OK = [
    (Cash, dict(balance=D("0"))),
    (Cash, dict(interest_rate=None)),
    (Cash, dict(interest_rate=D("100"))),
    (FixedDeposit, dict(rate=D("0"))),
    (Pf, dict(contributed=None)),
    (Pf, dict(interest_rate=D("100"))),
    (Bond, dict(face_value=None)),
    (Bond, dict(invested_amount=D("0"))),
    (MutualFund, dict(avg_nav=D("0"), invested_amount=D("0"))),
    (Nps, dict(contributed=D("0"))),
    (Gold, dict(invested_amount=D("0"))),
    (Other, dict(current_value=D("0"), invested_amount=None, acquired_on=None)),
    (Other, dict(acquired_on=D2)),
    (HoldingExit, dict(quantity=None, amount=D("0"), cost=D("0"), charges=D("0"))),
]


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[m.__table__ for m in MODELS])
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session
    engine.dispose()


def insert(db, model, **changes):
    db.add(model(**{**BASE[model], **changes}))
    db.commit()


@pytest.mark.parametrize("model", MODELS)
def test_valid_base_row_is_accepted(db, model):
    insert(db, model)


@pytest.mark.parametrize(
    ("name", "model", "changes"), VIOLATIONS, ids=[f"{v[0]}-{i}" for i, v in enumerate(VIOLATIONS)]
)
def test_violating_row_is_refused(db, name, model, changes):
    insert(db, model)
    with pytest.raises(IntegrityError, match=name):
        insert(db, model, **changes)
    db.rollback()


@pytest.mark.parametrize(
    ("model", "changes"), BOUNDARY_OK, ids=[f"{m.__name__}-{i}" for i, (m, _) in enumerate(BOUNDARY_OK)]
)
def test_boundary_values_are_accepted(db, model, changes):
    insert(db, model, **changes)


def test_every_violation_names_a_declared_constraint():
    declared = {
        c.name for m in MODELS for c in m.__table__.constraints if c.name and c.name.startswith("ck_")
    }
    assert {v[0] for v in VIOLATIONS} <= declared


def test_every_new_check_has_a_violation_case():
    covered = {v[0] for v in VIOLATIONS}
    for model in MODELS:
        for constraint in model.__table__.constraints:
            name = constraint.name or ""
            # Enum value checks (generated from str_enum) and the older SIP day check are not new.
            if name.startswith("ck_") and name != "ck_mf_sips_day_of_month":
                assert name in covered, name


def test_constraint_names_are_unique_across_tables():
    names = [
        c.name for t in Base.metadata.tables.values() for c in t.constraints if c.name is not None
    ]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("model", HOLDING_MODELS)
def test_holding_models_keep_user_deleted_index_and_checks(model):
    table = model.__table__
    indexes = {i.name: [c.name for c in i.columns] for i in table.indexes}
    assert indexes[f"ix_{table.name}_user_id_deleted_at"] == ["user_id", "deleted_at"]
    declared = {c.name for c in model._checks}
    assert declared
    assert declared <= {c.name for c in table.constraints}


def test_user_deleted_index_exists_in_the_database(db):
    names = {i["name"] for i in inspect(db.get_bind()).get_indexes("stocks")}
    assert "ix_stocks_user_id_deleted_at" in names


# --- one active funding per holding ---------------------------------------------------------


def test_second_active_funding_for_a_holding_is_refused(db):
    insert(db, HoldingFunding)
    with pytest.raises(IntegrityError, match="holding_fundings"):
        insert(db, HoldingFunding, cash_holding_id=2)
    db.rollback()


def test_refunded_funding_does_not_block_a_new_one(db):
    insert(db, HoldingFunding, refunded_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    insert(db, HoldingFunding)  # the holding was deleted (refunded) and funded again
    insert(db, HoldingFunding, refunded_at=datetime(2026, 1, 3, tzinfo=timezone.utc))


def test_different_holding_or_type_can_be_funded(db):
    insert(db, HoldingFunding)
    insert(db, HoldingFunding, holding_id=2)
    insert(db, HoldingFunding, asset_type="mf")
