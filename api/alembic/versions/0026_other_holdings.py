"""other_holdings (manually valued assets such as crypto)

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-02
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "other_holdings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("current_value", sa.Numeric(14, 2), nullable=False),
        sa.Column("value_date", sa.Date(), nullable=False),
        sa.Column("invested_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
    )
    op.create_index("ix_other_holdings_user_id", "other_holdings", ["user_id"])
    op.create_index(
        "ix_other_holdings_user_id_deleted_at", "other_holdings", ["user_id", "deleted_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_other_holdings_user_id_deleted_at", table_name="other_holdings")
    op.drop_index("ix_other_holdings_user_id", table_name="other_holdings")
    op.drop_table("other_holdings")
