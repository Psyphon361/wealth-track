from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MFScheme(Base):
    """AMFI mutual fund scheme master, refreshed daily from NAVAll.txt.

    The trigram index on lower(name) is created in migration 0004 (expression index with
    operator class, so it is not declared here).
    """

    __tablename__ = "mf_schemes"

    scheme_code: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(300))
    amc: Mapped[str | None] = mapped_column(String(200))
    amfi_category: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    plan: Mapped[str | None] = mapped_column(String(20))
    option: Mapped[str | None] = mapped_column(String(20))
    idcw_frequency: Mapped[str | None] = mapped_column(String(20))
    isin_growth_payout: Mapped[str | None] = mapped_column(String(20))
    isin_reinvest: Mapped[str | None] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class MFNavLatest(Base):
    """Latest NAV per scheme; kept apart from the static master so unchanged schemes aren't rewritten."""

    __tablename__ = "mf_nav_latest"

    scheme_code: Mapped[int] = mapped_column(
        ForeignKey("mf_schemes.scheme_code", ondelete="CASCADE"),
        primary_key=True,
        autoincrement=False,
    )
    nav: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    nav_date: Mapped[date]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
