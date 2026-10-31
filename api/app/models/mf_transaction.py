from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class MFTransaction(Base):
    """A purchase or redemption of a mutual fund holding, stored from a CAS import."""

    __tablename__ = "mf_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    mutual_fund_id: Mapped[int] = mapped_column(
        ForeignKey("mutual_funds.id", ondelete="CASCADE"), index=True
    )
    txn_date: Mapped[date]
    kind: Mapped[str] = mapped_column(
        str_enum("purchase", "redemption", name="mf_txn_kind")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    units: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
