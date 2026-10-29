"""bonds.invested_amount (total invested; face value no longer user input)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bonds", sa.Column("invested_amount", sa.Numeric(14, 2), nullable=True))
    op.execute("UPDATE bonds SET invested_amount = ROUND(quantity * purchase_price, 2)")
    op.alter_column("bonds", "invested_amount", nullable=False)


def downgrade() -> None:
    op.drop_column("bonds", "invested_amount")
