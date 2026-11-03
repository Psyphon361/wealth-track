from datetime import datetime

from sqlalchemy import DateTime, Enum, Index, Text, event, func
from sqlalchemy.orm import (
    Mapped,
    ORMExecuteState,
    Session,
    declared_attr,
    mapped_column,
    with_loader_criteria,
)

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
    # Soft delete: set when the holding is deleted; rows are purged after 30 days.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @declared_attr.directive
    def __table_args__(cls) -> tuple:
        # Every holding query filters by user and (via the soft-delete criteria) deleted_at.
        return (Index(f"ix_{cls.__tablename__}_user_id_deleted_at", "user_id", "deleted_at"),)


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state: ORMExecuteState) -> None:
    """Hide soft-deleted holdings from every ORM query (entity, column and subquery uses).

    Opt out with `.execution_options(include_deleted=True)`. Statements that bypass the ORM
    (Core `insert(Model.__table__)`, raw SQL) are not covered and must filter explicitly.
    """
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(
                TimestampedMixin,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )
