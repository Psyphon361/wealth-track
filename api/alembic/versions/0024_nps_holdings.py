"""nps_holdings (one row per held NPS scheme: units, total contributed, start date)

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nps_holdings",
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
        sa.Column(
            "scheme_id",
            sa.String(20),
            sa.ForeignKey("nps_master.scheme_id"),
            nullable=False,
        ),
        sa.Column("units", sa.Numeric(14, 4), nullable=False),
        sa.Column("contributed", sa.Numeric(14, 2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
    )
    op.create_index("ix_nps_holdings_user_id", "nps_holdings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_nps_holdings_user_id", table_name="nps_holdings")
    op.drop_table("nps_holdings")
