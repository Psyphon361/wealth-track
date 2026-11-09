"""Paid from: taking the price of a new holding off a Cash & Savings account.

The amount is the new holding's invested amount. `plan` checks the request and works out the
amounts without writing; `apply` debits the account and records the funding. Deleting the holding
refunds the account (`refund`), restoring it debits again (`restore`). None of these commit: the
router commits once, so a failure anywhere leaves nothing written.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import Cash, HoldingExit, HoldingFunding
from app.schemas.exits import CASH_ACCOUNT_ERROR
from app.schemas.fundings import (
    PAID_FROM_EDIT_DELETED_ERROR,
    PAID_FROM_EDIT_GONE_NOTE,
    PAID_FROM_EDIT_NOT_IN_SYNC_NOTE,
    PAID_FROM_EDIT_TOO_MUCH_ERROR,
    PAID_FROM_EDIT_ZERO_ERROR,
    PAID_FROM_OTHER_AMOUNT_ERROR,
    PAID_FROM_TOO_MUCH_ERROR,
    PaidFromBody,
)
from app.services import sip as sip_service
from app.services import valuation

_CENT = Decimal("0.01")
_ZERO = Decimal("0")

# Attribute holding the day each type starts on (the funding date); cash and pf use their balance date.
START_ATTR = {
    "fd": "start_date",
    "rd": "start_date",
    "stock": "buy_date",
    "bond": "purchase_date",
    "mf": "purchase_date",
    "nps": "start_date",
    "gold": "purchase_date",
    "cash": "balance_date",
    "pf": "balance_date",
    "other": "acquired_on",
}


class FundingError(Exception):
    """One field of paid_from is invalid; the router turns it into a 422 pointing at `loc`."""

    def __init__(self, loc: tuple[str, ...], message: str, value: Any = None):
        super().__init__(message)
        self.loc = loc
        self.message = message
        self.value = value


class FundingConflict(Exception):
    """The funding can't be re-applied (409)."""

    def __init__(self, message: str, description: str):
        super().__init__(message)
        self.message = message
        self.description = description


@dataclass
class FundingPlan:
    cash: Cash
    amount: Decimal
    funded_on: date
    from_exit_id: int | None


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def amount_for(slug: str, values: Mapping[str, Any], today: date) -> Decimal | None:
    """What a new holding costs: its invested amount. None for Other without one."""
    if slug == "fd":
        return money(values["principal"])
    if slug == "rd":
        paid, _grown = valuation.rd_position(SimpleNamespace(**values), today)
        return money(Decimal(str(values["monthly_instalment"])) * paid)
    if slug == "stock":
        return money(Decimal(str(values["quantity"])) * Decimal(str(values["avg_buy_price"])))
    if slug == "nps":
        return money(values["contributed"])
    if slug == "cash":
        return money(values["balance"])
    if slug == "pf":
        picked = values.get("contributed")
        return money(picked if picked is not None else values["balance"])
    invested = values.get("invested_amount")  # bond, mf, gold, other
    return money(invested) if invested is not None else None


def funded_on_for(slug: str, values: Mapping[str, Any], today: date) -> date:
    return values.get(START_ATTR[slug]) or today


def plan(
    db: Session, user_id: int, slug: str, values: Mapping[str, Any], paid: PaidFromBody, today: date
) -> FundingPlan | None:
    """Check `paid_from` and work out what to take. Raises FundingError (422). No writes.

    Returns None when the holding costs nothing so far (an RD with no instalment paid yet).
    """
    cash_loc = ("paid_from", "cash_id")
    found = True
    if paid.from_exit_id is not None:
        # Lock the exit FIRST (undo locks exit, holding, then cash) so an undo of it and this
        # reinvest serialise without a lock-order deadlock.
        found = (
            db.scalar(
                sa.select(HoldingExit.id)
                .where(HoldingExit.id == paid.from_exit_id, HoldingExit.user_id == user_id)
                .with_for_update()
            )
            is not None
        )
    cash = db.scalars(
        sa.select(Cash).where(Cash.id == paid.cash_id, Cash.user_id == user_id).with_for_update(of=Cash)
    ).first()
    if cash is None:
        raise FundingError(cash_loc, CASH_ACCOUNT_ERROR, paid.cash_id)
    if not found:
        raise FundingError(("paid_from", "from_exit_id"), CASH_ACCOUNT_ERROR, paid.from_exit_id)
    amount = amount_for(slug, values, today)
    if amount is None:
        raise FundingError(cash_loc, PAID_FROM_OTHER_AMOUNT_ERROR)
    if amount > Decimal(str(cash.balance)):
        raise FundingError(cash_loc, PAID_FROM_TOO_MUCH_ERROR, amount)
    if amount <= 0:
        return None
    return FundingPlan(cash, amount, funded_on_for(slug, values, today), paid.from_exit_id)


def apply(db: Session, user_id: int, slug: str, holding_id: int, p: FundingPlan) -> HoldingFunding:
    """Take the money off the account and record the funding."""
    cash = p.cash
    previous_date = cash.balance_date
    cash.balance = Decimal(str(cash.balance)) - p.amount
    cash.balance_date = max(previous_date, p.funded_on)
    row = HoldingFunding(
        user_id=user_id,
        asset_type=slug,
        holding_id=holding_id,
        cash_holding_id=cash.id,
        amount=p.amount,
        funded_on=p.funded_on,
        from_exit_id=p.from_exit_id,
        prev_balance_date=previous_date,
    )
    db.add(row)
    return row


# Types whose amount is a fixed purchase cost: editing it moves money on the funding account. For
# cash, pf, nps and rd the amount is a running figure users update routinely, so an edit moves none.
EDIT_ADJUSTS = ("fd", "stock", "bond", "mf", "gold", "other")
_COST_ATTRS = {
    "fd": ("principal",),
    "stock": ("quantity", "avg_buy_price"),
    "bond": ("invested_amount",),
    "mf": ("invested_amount",),
    "gold": ("invested_amount",),
    "other": ("invested_amount",),
}
_COST_FIELD = {"fd": "principal", "bond": "invested_amount", "mf": "invested_amount",
               "gold": "invested_amount", "other": "invested_amount"}  # fmt: skip


def stored_cost(slug: str, record: Any) -> Decimal | None:
    """The cost a stored holding has now (what `amount_for` says of its saved values)."""
    return amount_for(slug, {a: getattr(record, a) for a in _COST_ATTRS[slug]}, date.today())


@dataclass
class EditPlan:
    """What a cost edit does to the funding account (built under the locks, applied by `apply_edit`)."""

    funding: HoldingFunding | None  # None when no money moves
    cash: Cash | None
    new_amount: Decimal | None
    note: str | None = None
    line: str | None = None


def _edit_field(slug: str, record: Any, values: Mapping[str, Any]) -> str:
    """The form field a cost change is blamed on."""
    if slug != "stock":
        return _COST_FIELD[slug]
    for field in ("quantity", "avg_buy_price"):
        if Decimal(str(getattr(record, field))) != Decimal(str(values[field])):
            return field
    return "quantity"


def _name_of(db: Session, user_id: int, cash_id: int | None) -> str | None:
    if cash_id is None:
        return None
    return db.scalar(
        sa.select(Cash.name)
        .where(Cash.id == cash_id, Cash.user_id == user_id)
        .execution_options(include_deleted=True)
    )


def plan_edit(
    db: Session, user_id: int, slug: str, record: Any, values: Mapping[str, Any]
) -> EditPlan | None:
    """Work out what editing the cost of `record` does to its funding account. No money is written.

    The caller holds the holding's row lock and has not applied `values` yet. Order: (1) did the cost
    change? (2) a funded cost may not drop to zero; (3) is the holding in sync with its funding?
    (4) the account is gone, deleted or short. Locks: holding, the funding row, then the account.
    Raises FundingError (422 on the cost field). Returns None when nothing about the funding changes.
    """
    if slug not in EDIT_ADJUSTS:
        return None
    today = date.today()
    old = stored_cost(slug, record)
    new = amount_for(slug, values, today)
    if new == old:
        return None
    funding = db.scalars(
        sa.select(HoldingFunding)
        .where(
            HoldingFunding.user_id == user_id,
            HoldingFunding.asset_type == slug,
            HoldingFunding.holding_id == record.id,
            HoldingFunding.refunded_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if funding is None:
        return None
    field = _edit_field(slug, record, values)
    shown = values.get(field)
    if new is None or new <= 0:
        raise FundingError((field,), PAID_FROM_EDIT_ZERO_ERROR, shown)
    paid = money(funding.amount)
    if old != paid:
        name = _name_of(db, user_id, funding.cash_holding_id)
        note = PAID_FROM_EDIT_NOT_IN_SYNC_NOTE.format(account=name or "its account")
        return EditPlan(None, None, None, note)
    cash = _cash_of(db, user_id, funding.cash_holding_id)
    if cash is None:  # purged: its money is no longer tracked
        return EditPlan(None, None, None, PAID_FROM_EDIT_GONE_NOTE)
    if cash.deleted_at is not None:
        raise FundingError((field,), PAID_FROM_EDIT_DELETED_ERROR.format(account=cash.name), shown)
    balance = Decimal(str(cash.balance))
    delta = new - paid
    if delta > balance:
        shortfall = sip_service.format_inr(delta - balance)
        message = PAID_FROM_EDIT_TOO_MUCH_ERROR.format(account=cash.name, shortfall=shortfall)
        raise FundingError((field,), message, shown)
    line = f"{cash.name}: {sip_service.format_inr(balance)} → {sip_service.format_inr(balance - delta)}"
    return EditPlan(funding, cash, new, None, line)


def apply_edit(p: EditPlan) -> None:
    """Move the difference between the account and the funding (balance date is left alone)."""
    if p.funding is None or p.cash is None or p.new_amount is None:
        return
    delta = p.new_amount - money(p.funding.amount)
    p.cash.balance = Decimal(str(p.cash.balance)) - delta
    p.funding.amount = p.new_amount


def _cash_of(db: Session, user_id: int, cash_id: int | None) -> Cash | None:
    """The user's account, active or soft-deleted; None when it was purged for good (its money is
    then not tracked)."""
    if cash_id is None:
        return None
    return db.scalars(
        sa.select(Cash)
        .where(Cash.id == cash_id, Cash.user_id == user_id)
        .with_for_update(of=Cash)
        .execution_options(include_deleted=True)
    ).first()


def _fundings(db: Session, user_id: int, slug: str, holding_id: int, refunded: bool):
    """The holding's funding rows, locked FOR UPDATE so a concurrent refund/restore waits."""
    return db.scalars(
        sa.select(HoldingFunding)
        .where(
            HoldingFunding.user_id == user_id,
            HoldingFunding.asset_type == slug,
            HoldingFunding.holding_id == holding_id,
            HoldingFunding.refunded_at.is_not(None)
            if refunded
            else HoldingFunding.refunded_at.is_(None),
        )
        .order_by(HoldingFunding.id)
        .with_for_update()
    ).all()


def refund(db: Session, user_id: int, slug: str, holding_id: int) -> None:
    """The holding was deleted: put its active fundings back into their accounts."""
    now = datetime.now(timezone.utc)
    for row in _fundings(db, user_id, slug, holding_id, refunded=False):
        cash = _cash_of(db, user_id, row.cash_holding_id)
        if cash is not None:
            cash.balance = Decimal(str(cash.balance)) + Decimal(str(row.amount))
        row.refunded_at = now


def restore(db: Session, user_id: int, slug: str, holding_id: int) -> None:
    """The holding was restored: take its refunded fundings out of their accounts again.

    Raises FundingConflict (409) when an account no longer has enough; the caller rolls back.
    """
    for row in _fundings(db, user_id, slug, holding_id, refunded=True):
        cash = _cash_of(db, user_id, row.cash_holding_id)
        if cash is not None:
            amount = Decimal(str(row.amount))
            if Decimal(str(cash.balance)) < amount:
                if cash.deleted_at is not None:  # can't be topped up until restored
                    shortfall = sip_service.format_inr(amount - Decimal(str(cash.balance)))
                    description = (
                        f"Restore {cash.name} from Recently deleted and add {shortfall} to it, "
                        "then restore."
                    )
                else:
                    description = "Update its balance, then restore."
                raise FundingConflict(f"Not enough in {cash.name}", description)
            cash.balance = Decimal(str(cash.balance)) - amount
        row.refunded_at = None


def reinvested_by_exit(
    db: Session, user_id: int, exit_ids: Iterable[int] | None = None
) -> dict[int, Decimal]:
    """{exit id: money of that exit put into holdings that still exist (active fundings)}."""
    stmt = (
        sa.select(HoldingFunding.from_exit_id, sa.func.sum(HoldingFunding.amount))
        .where(
            HoldingFunding.user_id == user_id,
            HoldingFunding.from_exit_id.is_not(None),
            HoldingFunding.refunded_at.is_(None),
        )
        .group_by(HoldingFunding.from_exit_id)
    )
    if exit_ids is not None:
        stmt = stmt.where(HoldingFunding.from_exit_id.in_(list(exit_ids)))
    return {exit_id: money(total) for exit_id, total in db.execute(stmt).all()}


def left_in_account(cash_added: Decimal | None, reinvested: Decimal) -> Decimal | None:
    """What of an exit's payout is still in its account: cash added less reinvested, never below 0."""
    if cash_added is None:
        return None
    return max(Decimal(str(cash_added)) - reinvested, _ZERO)


def paid_from_info(session: Session, user_id: int) -> dict[tuple[str, int], dict[str, Any]]:
    """{(type, holding id): the `paid_from` object of its active funding} (JSON-ready)."""
    account = Cash.__table__  # Core table: also finds the name of an account that was soft-deleted
    rows = session.execute(
        sa.select(
            HoldingFunding.asset_type,
            HoldingFunding.holding_id,
            HoldingFunding.cash_holding_id,
            HoldingFunding.amount,
            HoldingFunding.funded_on,
            account.c.name,
            account.c.deleted_at,
        )
        .outerjoin(account, account.c.id == HoldingFunding.cash_holding_id)
        .where(HoldingFunding.user_id == user_id, HoldingFunding.refunded_at.is_(None))
        .order_by(HoldingFunding.id)
    ).all()
    return {
        (slug, holding_id): {
            "cash_holding_id": cash_id,
            "cash_name": name,
            "amount": float(amount),
            "date": funded_on.isoformat(),
            "adjustable": slug in EDIT_ADJUSTS and cash_id is not None and deleted_at is None,
            "reason": _edit_reason(slug, cash_id, deleted_at),
        }
        for slug, holding_id, cash_id, amount, funded_on, name, deleted_at in rows
    }


def _edit_reason(slug: str, cash_id: int | None, deleted_at: Any) -> str | None:
    """Why editing the cost will not move money: type, account_gone, account_deleted (else None)."""
    if slug not in EDIT_ADJUSTS:
        return "type"
    if cash_id is None:
        return "account_gone"
    return "account_deleted" if deleted_at is not None else None


def apply_paid_from(
    groups: Iterable[Mapping[str, Any]],
    info: Mapping[tuple[str, int], Mapping[str, Any]],
    records: Mapping[str, Iterable[Any]] | None = None,
) -> None:
    """Set `paid_from` on the items of valued groups, in place.

    With the stored `records` (by type), an adjustable funding is also checked to be in sync: the
    holding's stored cost must equal what was taken, else editing moves no money (`out_of_sync`).
    """
    stored = {slug: {r.id: r for r in rows} for slug, rows in (records or {}).items()}
    for group in groups:
        slug = group["type"]
        for item in group["items"]:
            found = info.get((slug, item["id"]))
            if found is None:
                item["paid_from"] = None
                continue
            found = dict(found)
            record = stored.get(slug, {}).get(item["id"])
            if slug in EDIT_ADJUSTS and record is not None:
                cost = stored_cost(slug, record)
                if cost is None or cost != money(found["amount"]):
                    found["adjustable"] = False
                    found["reason"] = "out_of_sync"
            item["paid_from"] = found


def paid_from_text(amount: Decimal, cash_name: str) -> str:
    return f"{sip_service.format_inr(amount)} taken from {cash_name}"
