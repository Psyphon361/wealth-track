"""mutual_funds.invested_amount (total invested, user-entered)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-31
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mutual_funds", sa.Column("invested_amount", sa.Numeric(14, 2), nullable=True)
    )
    op.execute("UPDATE mutual_funds SET invested_amount = ROUND(units * avg_nav, 2)")
    op.alter_column("mutual_funds", "invested_amount", nullable=False)


def downgrade() -> None:
    op.drop_column("mutual_funds", "invested_amount")
