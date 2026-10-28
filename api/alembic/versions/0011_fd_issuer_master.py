"""fd_issuer_master (banks, NBFCs, HFCs, post office) and issuer_id link on FDs and RDs

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-28
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CATEGORIES = (
    "public_sector", "private_sector", "small_finance", "foreign", "regional_rural",
    "local_area", "payments", "state_coop", "district_coop", "urban_coop", "nbfc", "hfc",
    "post_office",
)  # fmt: skip


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "fd_issuer_master",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("short_name", sa.String(100), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                *CATEGORIES,
                name="fd_issuer_category", native_enum=False, create_constraint=True, length=20,
            ),
            nullable=False,
        ),
        sa.Column("regulator", sa.String(10), nullable=True),
        sa.Column("reg_no", sa.String(40), nullable=True),
        sa.Column("dicgc_insured", sa.Boolean(), nullable=True),
        sa.Column("accepts_deposits", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("merged_into_id", sa.Integer(), nullable=True),
        sa.Column("merged_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column(
            "sources", ARRAY(sa.String(20)), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_fd_issuer_master_code"),
        sa.ForeignKeyConstraint(
            ["merged_into_id"],
            ["fd_issuer_master.id"],
            name="fk_fd_issuer_master_merged_into",
            ondelete="SET NULL",
        ),
    )
    op.execute(
        "CREATE INDEX ix_fd_issuer_master_name_trgm ON fd_issuer_master "
        "USING gin (lower(name) gin_trgm_ops)"
    )
    for table in ("fixed_deposits", "recurring_deposits"):
        op.add_column(table, sa.Column("issuer_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_issuer_id",
            table,
            "fd_issuer_master",
            ["issuer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_issuer_id", table, ["issuer_id"])


def downgrade() -> None:
    for table in ("recurring_deposits", "fixed_deposits"):
        op.drop_index(f"ix_{table}_issuer_id", table_name=table)
        op.drop_constraint(f"fk_{table}_issuer_id", table, type_="foreignkey")
        op.drop_column(table, "issuer_id")
    op.execute("DROP INDEX IF EXISTS ix_fd_issuer_master_name_trgm")
    op.drop_table("fd_issuer_master")
    # pg_trgm is left installed: dropping an extension may affect other objects.
