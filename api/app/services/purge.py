"""Soft-delete retention: holdings deleted more than 30 days ago are removed for good."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Delete, delete
from sqlalchemy.orm import Session

from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    MutualFund,
    Nps,
    Pf,
    RecurringDeposit,
    Stock,
)

RETENTION_DAYS = 30

# type slug -> model, same slugs as routers.assets.REGISTRY
HOLDING_MODELS = {
    "fd": FixedDeposit,
    "rd": RecurringDeposit,
    "stock": Stock,
    "bond": Bond,
    "mf": MutualFund,
    "nps": Nps,
    "gold": Gold,
    "cash": Cash,
    "pf": Pf,
}


def purge_statement(model, cutoff: datetime) -> Delete:
    return delete(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff)


def purge_deleted(session: Session, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    """Hard-delete holdings (all users) soft-deleted more than `older_than_days` ago.

    mf_transactions go with their fund through the ON DELETE CASCADE foreign key.
    Returns the number of rows removed per type slug.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    counts: dict[str, int] = {}
    for slug, model in HOLDING_MODELS.items():
        result = session.execute(purge_statement(model, cutoff).execution_options(include_deleted=True))
        counts[slug] = result.rowcount
    session.commit()
    return counts
