"""gold_rate_latest and gold_rate_history (IBJA gold rates per gram by purity)

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gold_rate_latest",
        sa.Column("purity", sa.String(length=3), primary_key=True),
        sa.Column("rate_per_gram", sa.Numeric(12, 2), nullable=False),
        sa.Column("rate_date", sa.Date(), nullable=False),
        sa.Column("session", sa.String(length=2), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "gold_rate_history",
        sa.Column("purity", sa.String(length=3), primary_key=True),
        sa.Column("rate_date", sa.Date(), primary_key=True),
        sa.Column("rate_per_gram", sa.Numeric(12, 2), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gold_rate_history")
    op.drop_table("gold_rate_latest")
