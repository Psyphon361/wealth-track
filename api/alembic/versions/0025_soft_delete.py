"""soft delete: deleted_at on every holding table

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "fixed_deposits",
    "recurring_deposits",
    "stocks",
    "bonds",
    "mutual_funds",
    "nps_holdings",
    "gold_holdings",
    "cash_holdings",
    "pf_holdings",
)


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_user_id_deleted_at", table, ["user_id", "deleted_at"])


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_user_id_deleted_at", table_name=table)
        op.drop_column(table, "deleted_at")
