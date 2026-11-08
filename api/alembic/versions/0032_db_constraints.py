"""check constraints on holding amounts and dates, one active funding per holding

Plain (validated) constraints in one transaction: a violating row fails the whole migration.
Run scripts/preflight_0032.sql first; every count must be 0.

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-08
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, constraint name, expression); same as the CheckConstraints on the models.
CHECKS: tuple[tuple[str, str, str], ...] = (
    ("fixed_deposits", "ck_fixed_deposits_principal_positive", "principal > 0"),
    ("fixed_deposits", "ck_fixed_deposits_rate_range", "rate >= 0 AND rate <= 100"),
    (
        "fixed_deposits",
        "ck_fixed_deposits_tenure_positive",
        "tenure_years + tenure_months + tenure_days > 0",
    ),
    (
        "recurring_deposits",
        "ck_recurring_deposits_instalment_positive",
        "monthly_instalment > 0",
    ),
    ("recurring_deposits", "ck_recurring_deposits_rate_range", "rate >= 0 AND rate <= 100"),
    (
        "recurring_deposits",
        "ck_recurring_deposits_tenure_positive",
        "tenure_years + tenure_months + tenure_days > 0",
    ),
    ("stocks", "ck_stocks_quantity_positive", "quantity > 0"),
    ("stocks", "ck_stocks_avg_buy_price_positive", "avg_buy_price > 0"),
    ("bonds", "ck_bonds_quantity_positive", "quantity > 0"),
    ("bonds", "ck_bonds_purchase_price_positive", "purchase_price > 0"),
    ("bonds", "ck_bonds_invested_nonnegative", "invested_amount >= 0"),
    ("bonds", "ck_bonds_face_value_positive", "face_value IS NULL OR face_value > 0"),
    ("bonds", "ck_bonds_maturity_after_purchase", "maturity_date > purchase_date"),
    ("mutual_funds", "ck_mutual_funds_units_positive", "units > 0"),
    ("mutual_funds", "ck_mutual_funds_avg_nav_nonnegative", "avg_nav >= 0"),
    ("mutual_funds", "ck_mutual_funds_invested_nonnegative", "invested_amount >= 0"),
    ("nps_holdings", "ck_nps_holdings_units_positive", "units > 0"),
    ("nps_holdings", "ck_nps_holdings_contributed_nonnegative", "contributed >= 0"),
    ("gold_holdings", "ck_gold_holdings_weight_positive", "weight_grams > 0"),
    ("gold_holdings", "ck_gold_holdings_invested_nonnegative", "invested_amount >= 0"),
    ("cash_holdings", "ck_cash_holdings_balance_nonnegative", "balance >= 0"),
    (
        "cash_holdings",
        "ck_cash_holdings_rate_range",
        "interest_rate IS NULL OR (interest_rate >= 0 AND interest_rate <= 100)",
    ),
    ("pf_holdings", "ck_pf_holdings_balance_nonnegative", "balance >= 0"),
    ("pf_holdings", "ck_pf_holdings_rate_range", "interest_rate >= 0 AND interest_rate <= 100"),
    (
        "pf_holdings",
        "ck_pf_holdings_contributed_nonnegative",
        "contributed IS NULL OR contributed >= 0",
    ),
    ("other_holdings", "ck_other_holdings_value_nonnegative", "current_value >= 0"),
    (
        "other_holdings",
        "ck_other_holdings_invested_nonnegative",
        "invested_amount IS NULL OR invested_amount >= 0",
    ),
    (
        "other_holdings",
        "ck_other_holdings_acquired_before_value",
        "acquired_on IS NULL OR acquired_on <= value_date",
    ),
    (
        "holding_exits",
        "ck_holding_exits_quantity_positive",
        "quantity IS NULL OR quantity > 0",
    ),
    ("holding_exits", "ck_holding_exits_amount_nonnegative", "amount >= 0"),
    ("holding_exits", "ck_holding_exits_cost_nonnegative", "cost >= 0"),
    ("holding_exits", "ck_holding_exits_charges_nonnegative", "charges >= 0"),
    ("holding_fundings", "ck_holding_fundings_amount_positive", "amount > 0"),
    ("mf_sips", "ck_mf_sips_amount_positive", "amount > 0"),
    ("mf_sips", "ck_mf_sips_end_after_start", "end_date IS NULL OR end_date >= start_date"),
    ("mf_transactions", "ck_mf_transactions_amount_positive", "amount > 0"),
    ("mf_transactions", "ck_mf_transactions_units_positive", "units > 0"),
)


def upgrade() -> None:
    for table, name, expression in CHECKS:
        op.create_check_constraint(name, table, sa.text(expression))
    op.create_index(
        "uq_holding_fundings_active",
        "holding_fundings",
        ["asset_type", "holding_id"],
        unique=True,
        postgresql_where=sa.text("refunded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_holding_fundings_active", table_name="holding_fundings")
    for table, name, _expression in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
