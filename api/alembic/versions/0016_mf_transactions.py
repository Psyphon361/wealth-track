"""mf_transactions (purchases and redemptions from CAS imports, for XIRR)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mf_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mutual_fund_id",
            sa.Integer(),
            sa.ForeignKey("mutual_funds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("units", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('purchase', 'redemption')", name="mf_txn_kind"),
    )
    op.create_index("ix_mf_transactions_mutual_fund_id", "mf_transactions", ["mutual_fund_id"])


def downgrade() -> None:
    op.drop_index("ix_mf_transactions_mutual_fund_id", table_name="mf_transactions")
    op.drop_table("mf_transactions")
