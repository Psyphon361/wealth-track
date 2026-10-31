"""gold_holdings (physical and digital gold, valued at IBJA per-gram rates)

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def str_enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    op.create_table(
        "gold_holdings",
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
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "form",
            str_enum("jewellery", "coin", "bar", "digital", name="gold_form"),
            nullable=False,
        ),
        sa.Column(
            "purity",
            str_enum("999", "995", "916", "750", "585", name="gold_purity"),
            nullable=False,
        ),
        sa.Column("weight_grams", sa.Numeric(12, 3), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("invested_amount", sa.Numeric(14, 2), nullable=False),
    )
    op.create_index("ix_gold_holdings_user_id", "gold_holdings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_gold_holdings_user_id", table_name="gold_holdings")
    op.drop_table("gold_holdings")
