"""silver: metal column on gold rates and holdings, purity 925 allowed on holdings

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def str_enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


def upgrade() -> None:
    for table, key in (
        ("gold_rate_latest", ["metal", "purity"]),
        ("gold_rate_history", ["metal", "purity", "rate_date"]),
    ):
        op.add_column(
            table, sa.Column("metal", sa.String(6), nullable=False, server_default="gold")
        )
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, key)

    op.add_column(
        "gold_holdings",
        sa.Column(
            "metal",
            str_enum("gold", "silver", name="gold_metal"),
            nullable=False,
            server_default="gold",
        ),
    )
    op.drop_constraint("gold_purity", "gold_holdings", type_="check")
    op.create_check_constraint(
        "gold_purity",
        "gold_holdings",
        "purity IN ('999', '995', '916', '750', '585', '925')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM gold_holdings WHERE metal = 'silver'")
    op.drop_constraint("gold_purity", "gold_holdings", type_="check")
    op.create_check_constraint(
        "gold_purity", "gold_holdings", "purity IN ('999', '995', '916', '750', '585')"
    )
    op.drop_constraint("gold_metal", "gold_holdings", type_="check")
    op.drop_column("gold_holdings", "metal")

    for table, key in (
        ("gold_rate_history", ["purity", "rate_date"]),
        ("gold_rate_latest", ["purity"]),
    ):
        op.execute(f"DELETE FROM {table} WHERE metal = 'silver'")
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, key)
        op.drop_column(table, "metal")
