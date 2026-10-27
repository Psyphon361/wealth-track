from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class BondMaster(Base):
    """Listed bonds (NSE debt segment, SGBs), refreshed from exchange files.

    The trigram index on lower(name) is created in migration 0006 (expression index with
    operator class, so it is not declared here).
    """

    __tablename__ = "bond_master"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    issuer: Mapped[str | None] = mapped_column(String(300))
    nse_symbol: Mapped[str | None] = mapped_column(String(50))
    nse_series: Mapped[str | None] = mapped_column(String(10))
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    coupon_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    maturity_date: Mapped[date | None]
    bond_type: Mapped[str] = mapped_column(
        str_enum("government", "corporate", "tax_free", "sgb", "other", name="bond_master_type")
    )
    issue_date: Mapped[date | None]
    issue_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rating: Mapped[str | None] = mapped_column(String(100))
    rating_agency: Mapped[str | None] = mapped_column(String(100))
    rating_as_of: Mapped[date | None]
    coupon_type: Mapped[str | None] = mapped_column(String(20))
    interest_frequency: Mapped[str | None] = mapped_column(String(20))
    issue_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    issuer_ownership: Mapped[str | None] = mapped_column(String(10))
    issue_mode: Mapped[str | None] = mapped_column(String(10))
    is_perpetual: Mapped[bool | None] = mapped_column(Boolean)  # NULL = unknown (no NSDL data)
    nsdl_status: Mapped[str | None] = mapped_column(String(10))
    sources: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default=text("'{}'::varchar[]"), default=list
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[date | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
