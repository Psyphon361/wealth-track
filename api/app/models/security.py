from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import str_enum


class Security(Base):
    """Listed stock / ETF / bond master (NSE + BSE), refreshed from exchange files.

    The trigram index on lower(name) is created in migration 0006 (expression index with
    operator class, so it is not declared here).
    """

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(12), unique=True)
    kind: Mapped[str] = mapped_column(str_enum("stock", "etf", "bond", name="security_kind"))
    name: Mapped[str] = mapped_column(String(300))
    nse_symbol: Mapped[str | None] = mapped_column(String(50))
    nse_series: Mapped[str | None] = mapped_column(String(10))
    bse_code: Mapped[str | None] = mapped_column(String(10))
    bse_symbol: Mapped[str | None] = mapped_column(String(50))
    bse_group: Mapped[str | None] = mapped_column(String(10))
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    coupon_rate: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    maturity_date: Mapped[date | None]
    issuer: Mapped[str | None] = mapped_column(String(300))
    bond_type: Mapped[str | None] = mapped_column(
        str_enum("government", "corporate", "tax_free", "sgb", "other", name="security_bond_type")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[date | None]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
