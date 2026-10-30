"""stock_price_latest (last price per stock_master row)

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_price_latest",
        sa.Column(
            "master_id",
            sa.Integer(),
            sa.ForeignKey("stock_master.id", ondelete="CASCADE"),
            primary_key=True,
            autoincrement=False,
        ),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("prev_close", sa.Numeric(14, 2), nullable=True),
        sa.Column("price_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("stock_price_latest")
