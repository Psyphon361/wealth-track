from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class NpsMaster(Base):
    """NPS Trust scheme master, refreshed daily from the NAV report.

    The trigram index on lower(scheme_name) (migration 0023) is declared below the class.
    """

    __tablename__ = "nps_master"

    scheme_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    pfm_code: Mapped[str] = mapped_column(String(20))
    pfm_name: Mapped[str] = mapped_column(String(200))
    scheme_name: Mapped[str] = mapped_column(String(300))
    tier: Mapped[str | None] = mapped_column(String(2))  # "I" | "II"
    asset_class: Mapped[str] = mapped_column(String(10))  # E | C | G | A | other
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


Index(
    "ix_nps_master_scheme_name_trgm",
    func.lower(NpsMaster.scheme_name).label("scheme_name_lower"),
    postgresql_using="gin",
    postgresql_ops={"scheme_name_lower": "gin_trgm_ops"},
)


class NpsNavLatest(Base):
    __tablename__ = "nps_nav_latest"

    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("nps_master.scheme_id", ondelete="CASCADE"), primary_key=True
    )
    nav: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    nav_date: Mapped[date]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class NpsNavHistory(Base):
    __tablename__ = "nps_nav_history"

    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("nps_master.scheme_id", ondelete="CASCADE"), primary_key=True
    )
    nav_date: Mapped[date] = mapped_column(primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(14, 4))


class NpsNavHistorySync(Base):
    """One row once a scheme's history backfill has run."""

    __tablename__ = "nps_nav_history_sync"

    scheme_id: Mapped[str] = mapped_column(
        ForeignKey("nps_master.scheme_id", ondelete="CASCADE"), primary_key=True
    )
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
