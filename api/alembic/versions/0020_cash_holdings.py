"""cash_holdings (bank savings/current balances and cash in hand)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def str_enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "cash_holdings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "kind",
            str_enum("savings", "current", "cash", "other", name="cash_kind"),
            nullable=False,
        ),
        sa.Column("balance", sa.Numeric(14, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("balance_date", sa.Date(), nullable=False),
    )
    op.create_index("ix_cash_holdings_user_id", "cash_holdings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_cash_holdings_user_id", table_name="cash_holdings")
    op.drop_table("cash_holdings")
