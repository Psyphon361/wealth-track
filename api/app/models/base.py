from datetime import datetime

from sqlalchemy import DateTime, Enum, Text, func
from sqlalchemy.orm import Mapped, mapped_column

COMPOUNDING_VALUES = ("monthly", "quarterly", "half_yearly", "yearly", "simple")


def str_enum(*values: str, name: str) -> Enum:
    """VARCHAR + CHECK constraint, no native Postgres enum type."""
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


class TimestampedMixin:
    id: Mapped[int] = mapped_column(primary_key=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
