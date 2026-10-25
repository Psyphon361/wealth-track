"""mf_schemes: AMFI scheme master + mutual_funds.scheme_code link

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "mf_schemes",
        sa.Column("scheme_code", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("amc", sa.String(200), nullable=True),
        sa.Column("amfi_category", sa.String(200), nullable=True),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("plan", sa.String(20), nullable=True),
        sa.Column("option", sa.String(20), nullable=True),
        sa.Column("idcw_frequency", sa.String(20), nullable=True),
        sa.Column("isin_growth_payout", sa.String(20), nullable=True),
        sa.Column("isin_reinvest", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scheme_code"),
    )
    op.create_table(
        "mf_nav_latest",
        sa.Column("scheme_code", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("nav", sa.Numeric(14, 4), nullable=False),
        sa.Column("nav_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scheme_code"),
        sa.ForeignKeyConstraint(
            ["scheme_code"], ["mf_schemes.scheme_code"], ondelete="CASCADE"
        ),
    )
    op.execute(
        "CREATE INDEX ix_mf_schemes_name_trgm ON mf_schemes USING gin (lower(name) gin_trgm_ops)"
    )
    op.add_column("mutual_funds", sa.Column("scheme_code", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_mutual_funds_scheme_code",
        "mutual_funds",
        "mf_schemes",
        ["scheme_code"],
        ["scheme_code"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_mutual_funds_scheme_code", "mutual_funds", type_="foreignkey")
    op.drop_column("mutual_funds", "scheme_code")
    op.drop_table("mf_nav_latest")
    op.execute("DROP INDEX IF EXISTS ix_mf_schemes_name_trgm")
    op.drop_table("mf_schemes")
    # pg_trgm is left installed: dropping an extension may affect other objects.
