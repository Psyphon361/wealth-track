from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class MfSip(Base):
    """A monthly mutual fund SIP: one instalment is added on `day_of_month` at that day's NAV."""

    __tablename__ = "mf_sips"
    __table_args__ = (
        Index("ix_mf_sips_user_id", "user_id"),
        CheckConstraint("day_of_month BETWEEN 1 AND 28", name="ck_mf_sips_day_of_month"),
        CheckConstraint("amount > 0", name="ck_mf_sips_amount_positive"),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date", name="ck_mf_sips_end_after_start"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # The holding the instalments go into; null until the first instalment creates it.
    mutual_fund_id: Mapped[int | None] = mapped_column(
        ForeignKey("mutual_funds.id", ondelete="SET NULL")
    )
    scheme_code: Mapped[int] = mapped_column(ForeignKey("mf_master.scheme_code"))
    platform: Mapped[str] = mapped_column(String(200))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    day_of_month: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[date]
    # First instalment to add; earlier due dates (or paused months) are never posted.
    post_from: Mapped[date]
    end_date: Mapped[date | None]
    status: Mapped[str] = mapped_column(
        str_enum("active", "paused", "stopped", name="mf_sip_status"), default="active"
    )
    # Due date (not NAV date) of the last instalment posted.
    last_posted_on: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MfSipSkip(Base):
    """One upcoming instalment the user chose to skip."""

    __tablename__ = "mf_sip_skips"
    __table_args__ = (UniqueConstraint("sip_id", "due_date", name="uq_mf_sip_skips_sip_due"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    sip_id: Mapped[int] = mapped_column(ForeignKey("mf_sips.id", ondelete="CASCADE"))
    due_date: Mapped[date]
