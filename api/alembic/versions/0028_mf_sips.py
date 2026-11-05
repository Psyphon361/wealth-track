"""mf_sips, mf_sip_skips and mf_transactions.sip_id (monthly mutual fund SIPs)

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mf_sips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "mutual_fund_id",
            sa.Integer(),
            sa.ForeignKey("mutual_funds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "scheme_code",
            sa.Integer(),
            sa.ForeignKey("mf_master.scheme_code"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(length=200), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("day_of_month", sa.SmallInteger(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("post_from", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_posted_on", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("status IN ('active', 'paused', 'stopped')", name="mf_sip_status"),
        sa.CheckConstraint("day_of_month BETWEEN 1 AND 28", name="ck_mf_sips_day_of_month"),
    )
    op.create_index("ix_mf_sips_user_id", "mf_sips", ["user_id"])
    op.create_table(
        "mf_sip_skips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "sip_id", sa.Integer(), sa.ForeignKey("mf_sips.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.UniqueConstraint("sip_id", "due_date", name="uq_mf_sip_skips_sip_due"),
    )
    op.add_column(
        "mf_transactions",
        sa.Column(
            "sip_id", sa.Integer(), sa.ForeignKey("mf_sips.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_unique_constraint(
        "uq_mf_transactions_sip_date", "mf_transactions", ["sip_id", "txn_date"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_mf_transactions_sip_date", "mf_transactions", type_="unique")
    op.drop_column("mf_transactions", "sip_id")
    op.drop_table("mf_sip_skips")
    op.drop_index("ix_mf_sips_user_id", table_name="mf_sips")
    op.drop_table("mf_sips")
