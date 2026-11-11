from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, UniqueConstraint, false, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class MFTransaction(Base):
    """A purchase or redemption of a mutual fund holding, stored from a CAS import."""

    __tablename__ = "mf_transactions"
    __table_args__ = (
        UniqueConstraint("sip_id", "txn_date", name="uq_mf_transactions_sip_date"),
        CheckConstraint("amount > 0", name="ck_mf_transactions_amount_positive"),
        CheckConstraint("units > 0", name="ck_mf_transactions_units_positive"),
    )

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
    # Set on instalments added by a SIP; the pair with txn_date stops one being posted twice.
    sip_id: Mapped[int | None] = mapped_column(ForeignKey("mf_sips.id", ondelete="SET NULL"))
    # True on a purchase the user added with Buy more (not from a CAS import or a SIP); a CAS
    # re-import keeps these after the statement date, and only these can be undone.
    manual: Mapped[bool] = mapped_column(server_default=false(), default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
