from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class GoldRateLatest(Base):
    """Latest IBJA gold rate per gram for each purity (999, 995, 916, 750, 585)."""

    __tablename__ = "gold_rate_latest"

    purity: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_per_gram: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rate_date: Mapped[date] = mapped_column(Date)
    session: Mapped[str] = mapped_column(String(2))
    source: Mapped[str] = mapped_column(String(20))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class GoldRateHistory(Base):
    """One IBJA gold rate per gram per purity per published date (PM overrides AM)."""

    __tablename__ = "gold_rate_history"

    purity: Mapped[str] = mapped_column(String(3), primary_key=True)
    rate_date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate_per_gram: Mapped[Decimal] = mapped_column(Numeric(12, 2))
