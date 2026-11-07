"""Soft-delete retention: holdings deleted more than 30 days ago are removed for good."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Delete, delete, select
from sqlalchemy.orm import Session

from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    HoldingExit,
    HoldingFunding,
    MutualFund,
    Nps,
    Other,
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
    "other": Other,
}


# Types that can have holding_exits rows (HoldingExit.asset_type).
EXIT_SLUGS = ("fd", "rd", "bond", "stock", "mf", "gold", "other")


def purge_statement(model, cutoff: datetime) -> Delete:
    return delete(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff)


def purge_deleted(session: Session, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    """Hard-delete holdings (all users) soft-deleted more than `older_than_days` ago.

    mf_transactions go with their fund through the ON DELETE CASCADE foreign key. holding_exits has
    no foreign key to the holding tables, so its rows for the purged holdings are deleted here, in
    the same transaction, and so are holding_fundings. Returns the number of rows removed per type
    slug, plus "exits" and "fundings" for the rows removed from those tables.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    counts: dict[str, int] = {}
    exits_removed = 0
    fundings_removed = 0
    for slug, model in HOLDING_MODELS.items():
        ids = list(
            session.scalars(
                select(model.id)
                .where(model.deleted_at.is_not(None), model.deleted_at < cutoff)
                .execution_options(include_deleted=True)
            )
        )
        if ids:
            if slug in EXIT_SLUGS:
                exits_removed += session.execute(
                    delete(HoldingExit).where(
                        HoldingExit.asset_type == slug, HoldingExit.holding_id.in_(ids)
                    )
                ).rowcount
            fundings_removed += session.execute(
                delete(HoldingFunding).where(
                    HoldingFunding.asset_type == slug, HoldingFunding.holding_id.in_(ids)
                )
            ).rowcount
        result = session.execute(purge_statement(model, cutoff).execution_options(include_deleted=True))
        counts[slug] = result.rowcount
    counts["exits"] = exits_removed
    counts["fundings"] = fundings_removed
    session.commit()
    return counts
