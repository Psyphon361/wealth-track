from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class MutualFund(TimestampedMixin, Base):
    __tablename__ = "mutual_funds"
    _checks = (
        CheckConstraint("units > 0", name="ck_mutual_funds_units_positive"),
        CheckConstraint("avg_nav >= 0", name="ck_mutual_funds_avg_nav_nonnegative"),
        CheckConstraint("invested_amount >= 0", name="ck_mutual_funds_invested_nonnegative"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scheme_name: Mapped[str] = mapped_column(String(200))
    scheme_code: Mapped[int | None] = mapped_column(
        ForeignKey("mf_master.scheme_code", ondelete="SET NULL")
    )
    platform: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(
        str_enum(
            "equity", "debt", "hybrid", "index", "elss", "liquid", "other",
            name="mf_category",
        )
    )
    units: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    avg_nav: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    invested_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    purchase_date: Mapped[date]
    # Set when every unit is sold; the row stays (status "sold") with its original units.
    closed_on: Mapped[date | None]
