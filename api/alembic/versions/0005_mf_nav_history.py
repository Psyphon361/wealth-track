"""mf_nav_history: per-scheme historical NAVs + sync bookkeeping

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mf_nav_history",
        sa.Column("scheme_code", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(14, 4), nullable=False),
        sa.PrimaryKeyConstraint("scheme_code", "nav_date"),
        sa.ForeignKeyConstraint(
            ["scheme_code"], ["mf_schemes.scheme_code"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "mf_nav_history_sync",
        sa.Column("scheme_code", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("first_date", sa.Date(), nullable=True),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheme_code"),
        sa.ForeignKeyConstraint(
            ["scheme_code"], ["mf_schemes.scheme_code"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("mf_nav_history_sync")
    op.drop_table("mf_nav_history")
