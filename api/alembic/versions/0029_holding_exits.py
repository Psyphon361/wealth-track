"""holding_exits (sales and maturity settlements) and closed_on on sellable holdings

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLOSABLE_TABLES = ("stocks", "bonds", "mutual_funds", "gold_holdings", "other_holdings")


def upgrade() -> None:
    for table in CLOSABLE_TABLES:
        op.add_column(table, sa.Column("closed_on", sa.Date(), nullable=True))
    op.create_table(
        "holding_exits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("exit_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("cost", sa.Numeric(14, 2), nullable=False),
        sa.Column("charges", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("destination", sa.String(length=20), nullable=False),
        sa.Column(
            "cash_holding_id",
            sa.Integer(),
            sa.ForeignKey("cash_holdings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("cash_added", sa.Numeric(14, 2), nullable=True),
        sa.Column("new_holding_id", sa.Integer(), nullable=True),
        sa.Column(
            "mf_transaction_id",
            sa.Integer(),
            sa.ForeignKey("mf_transactions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prev_state", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "asset_type IN ('fd', 'rd', 'bond', 'stock', 'mf', 'gold', 'other')",
            name="holding_exit_asset_type",
        ),
        sa.CheckConstraint("kind IN ('maturity', 'sale')", name="holding_exit_kind"),
        sa.CheckConstraint(
            "destination IN ('cash', 'renewed', 'none')", name="holding_exit_destination"
        ),
    )
    op.create_index(
        "ix_holding_exits_user_type_holding",
        "holding_exits",
        ["user_id", "asset_type", "holding_id"],
    )
    op.create_index(
        "uq_holding_exits_maturity",
        "holding_exits",
        ["asset_type", "holding_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'maturity'"),
    )


def downgrade() -> None:
    op.drop_index("uq_holding_exits_maturity", table_name="holding_exits")
    op.drop_index("ix_holding_exits_user_type_holding", table_name="holding_exits")
    op.drop_table("holding_exits")
    for table in CLOSABLE_TABLES:
        op.drop_column(table, "closed_on")
