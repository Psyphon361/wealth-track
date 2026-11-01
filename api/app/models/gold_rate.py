from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GoldRateLatest(Base):
    """Latest IBJA rate per gram for each (metal, purity): gold 999/995/916/750/585, silver 999.

    Silver 925 is never stored; it is derived from silver 999.
    """

    __tablename__ = "gold_rate_latest"

    metal: Mapped[str] = mapped_column(String(6), primary_key=True, server_default="gold")
    purity: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_per_gram: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rate_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GoldRateHistory(Base):
    """One IBJA rate per gram per (metal, purity) per published date (PM overrides AM)."""

    __tablename__ = "gold_rate_history"

    metal: Mapped[str] = mapped_column(String(6), primary_key=True, server_default="gold")
    purity: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate_per_gram: Mapped[Decimal] = mapped_column(Numeric(12, 2))
