"""NPS scheme master, latest NAV, NAV history and history sync

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "nps_master",
        sa.Column("scheme_id", sa.String(20), nullable=False),
        sa.Column("pfm_code", sa.String(20), nullable=False),
        sa.Column("pfm_name", sa.String(200), nullable=False),
        sa.Column("scheme_name", sa.String(300), nullable=False),
        sa.Column("tier", sa.String(2), nullable=True),
        sa.Column("asset_class", sa.String(10), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scheme_id"),
    )
    op.create_table(
        "nps_nav_latest",
        sa.Column("scheme_id", sa.String(20), nullable=False),
        sa.Column("nav", sa.Numeric(14, 4), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scheme_id"),
        sa.ForeignKeyConstraint(["scheme_id"], ["nps_master.scheme_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "nps_nav_history",
        sa.Column("scheme_id", sa.String(20), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column("nav", sa.Numeric(14, 4), nullable=False),
        sa.PrimaryKeyConstraint("scheme_id", "nav_date"),
        sa.ForeignKeyConstraint(["scheme_id"], ["nps_master.scheme_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "nps_nav_history_sync",
        sa.Column("scheme_id", sa.String(20), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheme_id"),
        sa.ForeignKeyConstraint(["scheme_id"], ["nps_master.scheme_id"], ondelete="CASCADE"),
    )
    op.execute(
        "CREATE INDEX ix_nps_master_scheme_name_trgm ON nps_master "
        "USING gin (lower(scheme_name) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nps_master_scheme_name_trgm")
    op.drop_table("nps_nav_history_sync")
    op.drop_table("nps_nav_history")
    op.drop_table("nps_nav_latest")
    op.drop_table("nps_master")
