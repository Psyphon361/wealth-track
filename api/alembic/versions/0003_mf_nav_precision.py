"""mutual_funds: avg_nav precision 2 -> 4 decimal places

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mutual_funds",
        "avg_nav",
        existing_type=sa.Numeric(14, 2),
        type_=sa.Numeric(14, 4),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mutual_funds",
        "avg_nav",
        existing_type=sa.Numeric(14, 4),
        type_=sa.Numeric(14, 2),
        existing_nullable=False,
    )
