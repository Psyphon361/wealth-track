from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampedMixin, str_enum


class Pf(TimestampedMixin, Base):
    __tablename__ = "pf_holdings"
    _checks = (
        CheckConstraint("balance >= 0", name="ck_pf_holdings_balance_nonnegative"),
        CheckConstraint(
            "interest_rate >= 0 AND interest_rate <= 100", name="ck_pf_holdings_rate_range"
        ),
        CheckConstraint(
            "contributed IS NULL OR contributed >= 0",
            name="ck_pf_holdings_contributed_nonnegative",
        ),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(str_enum("epf", "vpf", "ppf", name="pf_kind"))
    balance: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    balance_date: Mapped[date]
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    contributed: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    opened_on: Mapped[date | None]
