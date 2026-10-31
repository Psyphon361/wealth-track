"""stock_price_history and stock_price_history_sync (daily closes of held stocks)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_price_history",
        sa.Column(
            "master_id",
            sa.Integer(),
            sa.ForeignKey("stock_master.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("trade_date", sa.Date(), primary_key=True),
        sa.Column("close", sa.Numeric(14, 2), nullable=False),
    )
    op.create_table(
        "stock_price_history_sync",
        sa.Column(
            "master_id",
            sa.Integer(),
            sa.ForeignKey("stock_master.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("stock_price_history_sync")
    op.drop_table("stock_price_history")
