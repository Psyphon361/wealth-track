"""initial: five asset tables

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COMPOUNDING = ("monthly", "quarterly", "half_yearly", "yearly", "simple")


def str_enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def tenure_columns() -> list[sa.Column]:
    return [
        sa.Column(name, sa.Integer(), nullable=False, server_default="0")
        for name in ("tenure_years", "tenure_months", "tenure_days")
    ]


def upgrade() -> None:
    op.create_table(
        "fixed_deposits",
        *common_columns(),
        sa.Column("bank", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("principal", sa.Numeric(14, 2), nullable=False),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        *tenure_columns(),
        sa.Column(
            "compounding",
            str_enum(*COMPOUNDING, name="fd_compounding"),
            nullable=False,
            server_default="quarterly",
        ),
        sa.Column(
            "payout_type",
            str_enum("cumulative", "payout", name="fd_payout_type"),
            nullable=False,
        ),
    )
    op.create_table(
        "recurring_deposits",
        *common_columns(),
        sa.Column("bank", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("monthly_instalment", sa.Numeric(14, 2), nullable=False),
        sa.Column("rate", sa.Numeric(6, 3), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        *tenure_columns(),
        sa.Column(
            "compounding",
            str_enum(*COMPOUNDING, name="rd_compounding"),
            nullable=False,
            server_default="quarterly",
        ),
    )
    op.create_table(
        "stocks",
        *common_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=True),
        sa.Column(
            "exchange",
            str_enum("NSE", "BSE", name="stock_exchange"),
            nullable=False,
            server_default="NSE",
        ),
        sa.Column("broker", sa.String(200), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_buy_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("buy_date", sa.Date(), nullable=False),
    )
    op.create_table(
        "bonds",
        *common_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("isin", sa.String(20), nullable=True),
        sa.Column("issuer", sa.String(200), nullable=False),
        sa.Column(
            "bond_type",
            str_enum("government", "corporate", "tax_free", "sgb", "other", name="bond_type"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(200), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("purchase_price", sa.Numeric(14, 2), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
        sa.Column("ytm", sa.Numeric(6, 3), nullable=False),
        sa.Column("maturity_date", sa.Date(), nullable=False),
    )
    op.create_table(
        "mutual_funds",
        *common_columns(),
        sa.Column("scheme_name", sa.String(200), nullable=False),
        sa.Column("platform", sa.String(200), nullable=True),
        sa.Column(
            "category",
            str_enum(
                "equity", "debt", "hybrid", "index", "elss", "liquid", "other",
                name="mf_category",
            ),
            nullable=False,
        ),
        sa.Column("units", sa.Numeric(14, 3), nullable=False),
        sa.Column("avg_nav", sa.Numeric(14, 2), nullable=False),
        sa.Column("purchase_date", sa.Date(), nullable=False),
    )


def downgrade() -> None:
    for table in ("mutual_funds", "bonds", "stocks", "recurring_deposits", "fixed_deposits"):
        op.drop_table(table)
