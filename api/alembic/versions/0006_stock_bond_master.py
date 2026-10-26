"""stock_master + bond_master (NSE/BSE listings) and master_id link on stocks and bonds

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-26
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _common_tail() -> list[sa.Column]:
    return [
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen", sa.Date(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "stock_master",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "stock", "etf",
                name="stock_master_kind", native_enum=False, create_constraint=True, length=20,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("nse_symbol", sa.String(50), nullable=True),
        sa.Column("nse_series", sa.String(10), nullable=True),
        sa.Column("bse_code", sa.String(10), nullable=True),
        sa.Column("bse_symbol", sa.String(50), nullable=True),
        sa.Column("bse_group", sa.String(10), nullable=True),
        sa.Column("face_value", sa.Numeric(14, 2), nullable=True),
        *_common_tail(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", name="uq_stock_master_isin"),
    )
    op.execute(
        "CREATE INDEX ix_stock_master_name_trgm ON stock_master USING gin (lower(name) gin_trgm_ops)"
    )
    op.create_table(
        "bond_master",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("isin", sa.String(12), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("issuer", sa.String(300), nullable=True),
        sa.Column("nse_symbol", sa.String(50), nullable=True),
        sa.Column("nse_series", sa.String(10), nullable=True),
        sa.Column("face_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("coupon_rate", sa.Numeric(6, 3), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=True),
        sa.Column(
            "bond_type",
            sa.Enum(
                "government", "corporate", "tax_free", "sgb", "other",
                name="bond_master_type", native_enum=False, create_constraint=True, length=20,
            ),
            nullable=False,
        ),
        *_common_tail(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("isin", name="uq_bond_master_isin"),
    )
    op.execute(
        "CREATE INDEX ix_bond_master_name_trgm ON bond_master USING gin (lower(name) gin_trgm_ops)"
    )
    for table, master in (("stocks", "stock_master"), ("bonds", "bond_master")):
        op.add_column(table, sa.Column("master_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_master_id",
            table,
            master,
            ["master_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    for table in ("bonds", "stocks"):
        op.drop_constraint(f"fk_{table}_master_id", table, type_="foreignkey")
        op.drop_column(table, "master_id")
    op.execute("DROP INDEX IF EXISTS ix_bond_master_name_trgm")
    op.drop_table("bond_master")
    op.execute("DROP INDEX IF EXISTS ix_stock_master_name_trgm")
    op.drop_table("stock_master")
    # pg_trgm is left installed: dropping an extension may affect other objects.
