"""Soft-delete retention: holdings deleted more than 30 days ago are removed for good."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Delete, delete, select, text
from sqlalchemy.exc import OperationalError
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


# Lock order of the purge: type order, but cash last. A restore (or Paid From) locks its holding
# first and then the cash account that funded it, so purge must reach a cash account only after
# every other holding, or it could hold the account while a restore holds the holding.
LOCK_ORDER = tuple(slug for slug in HOLDING_MODELS if slug != "cash") + ("cash",)

# Postgres lock_timeout for the purge transaction.
PURGE_LOCK_TIMEOUT = "10s"
LOCK_NOT_AVAILABLE = "55P03"
DEADLOCK_DETECTED = "40P01"
# Both roll the whole purge back and are safe to retry.
RETRYABLE_SQLSTATES = (LOCK_NOT_AVAILABLE, DEADLOCK_DETECTED)


class PurgeLockTimeout(Exception):
    """A row the purge needed stayed locked past PURGE_LOCK_TIMEOUT, or Postgres reported a
    deadlock; nothing was deleted."""

    message = "Couldn't clean up deleted holdings"
    description = "A holding was busy (a lock conflict). Nothing was removed; try again shortly."

    def __init__(self) -> None:
        super().__init__(f"{self.message}: {self.description}")


def purge_statement(model, cutoff: datetime) -> Delete:
    return delete(model).where(model.deleted_at.is_not(None), model.deleted_at < cutoff)


def lock_purgeable_ids(session: Session, model, cutoff: datetime) -> list[int]:
    """Lock (FOR UPDATE, holding first) the holdings past retention and return their ids.

    A row locked by someone else (a restore in flight) is waited for; Postgres then re-evaluates
    the deleted_at condition on the committed row, so a row restored meanwhile drops out before
    any child row is touched.
    """
    return list(
        session.scalars(
            select(model.id)
            .where(model.deleted_at.is_not(None), model.deleted_at < cutoff)
            .order_by(model.id)
            .with_for_update(of=model)
            .execution_options(include_deleted=True)
        )
    )


def _lock_rows_pointing_at_cash(session: Session, cutoff: datetime) -> None:
    """Lock (by id) the exits, then the fundings, whose cash_holding_id is a purge-eligible account.

    The candidate cash ids are read without a lock: an account restored meanwhile only means a few
    extra rows are locked, and the cash lock right after re-checks the condition.
    """
    cash_ids = list(
        session.scalars(
            select(Cash.id)
            .where(Cash.deleted_at.is_not(None), Cash.deleted_at < cutoff)
            .execution_options(include_deleted=True)
        )
    )
    if not cash_ids:
        return
    for model in (HoldingExit, HoldingFunding):
        session.execute(
            select(model.id)
            .where(model.cash_holding_id.in_(cash_ids))
            .order_by(model.id)
            .with_for_update(of=model)
        ).all()


def purge_deleted(session: Session, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    """Hard-delete holdings (all users) soft-deleted more than `older_than_days` ago.

    mf_transactions go with their fund through the ON DELETE CASCADE foreign key. holding_exits has
    no foreign key to the holding tables, so its rows for the purged holdings are deleted here, in
    the same transaction, and so are holding_fundings. Returns the number of rows removed per type
    slug, plus "exits" and "fundings" for the rows removed from those tables.
    """
    try:
        return _purge(session, older_than_days)
    except OperationalError as exc:
        session.rollback()
        if getattr(exc.orig, "sqlstate", None) in RETRYABLE_SQLSTATES:
            raise PurgeLockTimeout() from exc
        raise
    except BaseException:
        session.rollback()
        raise


def _purge(session: Session, older_than_days: int) -> dict[str, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    if session.get_bind().dialect.name == "postgresql":
        # A stuck lock fails the run (all-or-nothing, rolled back) instead of hanging the cron.
        session.execute(
            text("SELECT set_config('lock_timeout', :value, true)"),
            {"value": PURGE_LOCK_TIMEOUT},
        )
    # Phase 1: lock every type's candidate holdings before any child row is touched. Deleting
    # exits or cash accounts SET NULLs holding_fundings rows (locking them), while a restore locks
    # its holding first and then its funding rows; taking all holding locks first keeps purge in
    # the same order and so cannot deadlock with a restore.
    # Deleting a cash account SET NULLs the exits and fundings that point at it, which needs their
    # row locks. An undo locks its exit, then its holding, then the cash account; a refund or
    # restore locks the holding, then its fundings, then the cash account. So those rows are
    # locked after every other holding and BEFORE the cash accounts. Global order: holdings by
    # type, exits pointing at purgeable cash, fundings pointing at purgeable cash, cash.
    locked: dict[str, list[int]] = {}
    for slug in LOCK_ORDER:
        if slug == "cash":
            _lock_rows_pointing_at_cash(session, cutoff)
        locked[slug] = lock_purgeable_ids(session, HOLDING_MODELS[slug], cutoff)
    # Phase 2: delete children and holdings, only the ids that survived the locks.
    counts: dict[str, int] = {}
    exits_removed = 0
    fundings_removed = 0
    for slug, model in HOLDING_MODELS.items():
        ids = locked[slug]
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
        if ids:
            result = session.execute(
                purge_statement(model, cutoff)
                .where(model.id.in_(ids))
                .execution_options(include_deleted=True)
            )
            counts[slug] = result.rowcount
        else:
            counts[slug] = 0
    counts["exits"] = exits_removed
    counts["fundings"] = fundings_removed
    session.commit()
    return counts
