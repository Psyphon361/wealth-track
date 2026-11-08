from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import COMPOUNDING_VALUES, TimestampedMixin, str_enum


class FixedDeposit(TimestampedMixin, Base):
    __tablename__ = "fixed_deposits"
    _checks = (
        CheckConstraint("principal > 0", name="ck_fixed_deposits_principal_positive"),
        CheckConstraint("rate >= 0 AND rate <= 100", name="ck_fixed_deposits_rate_range"),
        CheckConstraint(
            "tenure_years + tenure_months + tenure_days > 0",
            name="ck_fixed_deposits_tenure_positive",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bank: Mapped[str] = mapped_column(String(200))
    issuer_id: Mapped[int | None] = mapped_column(
        ForeignKey("fd_issuer_master.id", ondelete="SET NULL"), index=True
    )
    label: Mapped[str | None] = mapped_column(String(200))
    principal: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    start_date: Mapped[date]
    tenure_years: Mapped[int] = mapped_column(default=0, server_default="0")
    tenure_months: Mapped[int] = mapped_column(default=0, server_default="0")
    tenure_days: Mapped[int] = mapped_column(default=0, server_default="0")
    compounding: Mapped[str] = mapped_column(
        str_enum(*COMPOUNDING_VALUES, name="fd_compounding"),
        default="quarterly",
        server_default="quarterly",
    )
    payout_type: Mapped[str] = mapped_column(
        str_enum("cumulative", "payout", name="fd_payout_type")
    )
