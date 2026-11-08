from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Numeric, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class HoldingExit(Base):
    """How a holding left the portfolio: a sale (full or partial) or a maturity settlement.

    holding_id points at one of several tables (asset_type says which), so it has no foreign key.
    Undo deletes the row after restoring what `prev_state` recorded.
    """

    __tablename__ = "holding_exits"
    __table_args__ = (
        Index("ix_holding_exits_user_type_holding", "user_id", "asset_type", "holding_id"),
        # A deposit or bond is settled at most once.
        Index(
            "uq_holding_exits_maturity",
            "asset_type",
            "holding_id",
            unique=True,
            postgresql_where=text("kind = 'maturity'"),
            sqlite_where=text("kind = 'maturity'"),
        ),
        CheckConstraint(
            "quantity IS NULL OR quantity > 0", name="ck_holding_exits_quantity_positive"
        ),
        CheckConstraint("amount >= 0", name="ck_holding_exits_amount_nonnegative"),
        CheckConstraint("cost >= 0", name="ck_holding_exits_cost_nonnegative"),
        CheckConstraint("charges >= 0", name="ck_holding_exits_charges_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(
        str_enum("fd", "rd", "bond", "stock", "mf", "gold", "other", name="holding_exit_asset_type")
    )
    holding_id: Mapped[int]
    kind: Mapped[str] = mapped_column(str_enum("maturity", "sale", name="holding_exit_kind"))
    exit_date: Mapped[date]
    # Units, shares or grams sold; null for Other and for maturities.
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    # Money received after charges, and the cost basis of what left.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    charges: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, server_default="0")
    destination: Mapped[str] = mapped_column(
        str_enum("cash", "renewed", "none", name="holding_exit_destination")
    )
    cash_holding_id: Mapped[int | None] = mapped_column(
        ForeignKey("cash_holdings.id", ondelete="SET NULL")
    )
    cash_added: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    new_holding_id: Mapped[int | None]
    mf_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("mf_transactions.id", ondelete="SET NULL")
    )
    prev_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
