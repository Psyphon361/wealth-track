"""holding_fundings: "Paid from" a Cash & Savings account when a holding is added

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holding_fundings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("asset_type", sa.String(length=20), nullable=False),
        sa.Column("holding_id", sa.Integer(), nullable=False),
        sa.Column(
            "cash_holding_id",
            sa.Integer(),
            sa.ForeignKey("cash_holdings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("funded_on", sa.Date(), nullable=False),
        sa.Column(
            "from_exit_id",
            sa.Integer(),
            sa.ForeignKey("holding_exits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prev_balance_date", sa.Date(), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "asset_type IN ('fd', 'rd', 'stock', 'bond', 'mf', 'nps', 'gold', 'cash', 'pf', 'other')",
            name="holding_funding_asset_type",
        ),
    )
    op.create_index(
        "ix_holding_fundings_user_type_holding",
        "holding_fundings",
        ["user_id", "asset_type", "holding_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_holding_fundings_user_type_holding", table_name="holding_fundings")
    op.drop_table("holding_fundings")
