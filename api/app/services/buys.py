"""Buy more: adding a purchase to a mutual fund, and undoing it.

`record_mf_buy` and `undo_mf_buy` are the only writers of manual purchases. They never commit: the
router commits once, after taking the fund's row lock (FOR UPDATE OF mutual_funds). They do no
network call. A buy keeps `purchase_date` (a date before it is refused), writes a `manual`
purchase transaction (after an opening purchase for a fund with none) and adds the units and cost
to the holding. `undo_refusal` is the one rule that says whether a buy can be undone.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import HoldingExit, MFTransaction, MutualFund
from app.schemas.buys import (
    BUY_AMOUNT_TOO_SMALL_ERROR,
    BUY_DATE_BEFORE_LAST_SALE_ERROR,
    BUY_DUPLICATE_MESSAGE,
    BUY_UNDO_REFUSED_DESCRIPTION,
    BUY_UNDO_REFUSED_MESSAGE,
    BUY_UNDO_SALE_FIRST_DESCRIPTION,
    BUY_UNDO_SALE_FIRST_MESSAGE,
    BuyBody,
)
from app.schemas.assets import MAX_QUANTITY
from app.schemas.exits import EXIT_DATE_FUTURE_ERROR, SELL_DATE_BEFORE_PURCHASE_ERROR
from app.services import duplicates
from app.services import exits as exits_service
from app.services import sip as sip_service
from app.services.exits import ExitConflict, ExitError

_NAV = Decimal("0.0001")
_ZERO = Decimal("0")


class BuyNotFound(Exception):
    """The transaction is not a manual purchase of this holding (404 "Record not found")."""


class BuyDuplicate(Exception):
    """The same buy is already recorded (409; the caller may confirm)."""

    def __init__(self, holding: MutualFund):
        super().__init__(BUY_DUPLICATE_MESSAGE)
        self.holding = holding


@dataclass
class BuyOutcome:
    transaction: MFTransaction
    holding_name: str
    units_added: Decimal


@dataclass
class UndoBuyOutcome:
    holding_name: str
    units_removed: Decimal


def default_units(amount: Decimal, nav: Decimal) -> Decimal:
    """Units for an amount at a NAV, 3 dp (a statement's units override it)."""
    return (Decimal(str(amount)) / Decimal(str(nav))).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def last_sale_date(db: Session, holding_id: int) -> date | None:
    """Date of the holding's latest sale: sale exits and every redemption transaction (a CAS
    import can hold redemptions that have no exit row)."""
    exit_date = db.scalar(
        sa.select(sa.func.max(HoldingExit.exit_date)).where(
            HoldingExit.asset_type == "mf",
            HoldingExit.holding_id == holding_id,
            HoldingExit.kind == "sale",
        )
    )
    redemption = db.scalar(
        sa.select(sa.func.max(MFTransaction.txn_date)).where(
            MFTransaction.mutual_fund_id == holding_id, MFTransaction.kind == "redemption"
        )
    )
    dates = [d for d in (exit_date, redemption) if d is not None]
    return max(dates) if dates else None


def undo_refusal(holding: Any, txn: Any, last_sale: date | None) -> ExitConflict | None:
    """Why this manual purchase can't be undone, or None. The undo check and the `undoable` flag
    both use this."""
    if getattr(holding, "closed_on", None) is not None:
        return exits_service._not_active("mf", holding, date.today())
    # Purchases sort before redemptions on a day, so a same-day sale may have used these units.
    if last_sale is not None and last_sale >= txn.txn_date:
        return ExitConflict(BUY_UNDO_SALE_FIRST_MESSAGE, BUY_UNDO_SALE_FIRST_DESCRIPTION)
    left = Decimal(str(holding.units)) - Decimal(str(txn.units))
    left_invested = Decimal(str(holding.invested_amount)) - Decimal(str(txn.amount))
    if left <= 0 or left_invested < exits_service.remainder_floor("mf", left):
        return ExitConflict(BUY_UNDO_REFUSED_MESSAGE, BUY_UNDO_REFUSED_DESCRIPTION)
    return None


def _set_totals(holding: MutualFund, units: Decimal, invested: Decimal) -> None:
    holding.units = exits_service.units(units)
    holding.invested_amount = exits_service.money(invested)
    holding.avg_nav = (Decimal(str(holding.invested_amount)) / Decimal(str(holding.units))).quantize(
        _NAV, rounding=ROUND_HALF_UP
    )


def record_mf_buy(
    db: Session,
    holding: MutualFund,
    body: BuyBody,
    today: date,
    confirm_duplicate: bool = False,
) -> BuyOutcome:
    """Add a purchase to a locked, freshly read fund. Raises ExitConflict (409), ExitError (422)
    or BuyDuplicate (409). No commit."""
    conflict = exits_service._not_active("mf", holding, today)
    if conflict is not None:
        raise conflict
    if body.date > today:
        raise ExitError(("date",), EXIT_DATE_FUTURE_ERROR, body.date)
    if body.date < holding.purchase_date:
        raise ExitError(("date",), SELL_DATE_BEFORE_PURCHASE_ERROR, body.date)
    last_sale = last_sale_date(db, holding.id)
    if last_sale is not None and body.date < last_sale:
        raise ExitError(("date",), BUY_DATE_BEFORE_LAST_SALE_ERROR, body.date)

    amount = exits_service.money(body.amount)
    units = body.units if body.units is not None else default_units(amount, body.nav)
    units = exits_service.units(units)
    if units <= 0:
        raise ExitError(("units",), "Must be greater than 0", units)
    if units > MAX_QUANTITY:
        raise ExitError(("units",), "Must be at most 1 crore", units)

    new_units = Decimal(str(holding.units)) + units
    new_invested = Decimal(str(holding.invested_amount)) + amount
    if new_invested < exits_service.remainder_floor("mf", new_units):
        raise ExitError(("amount",), BUY_AMOUNT_TOO_SMALL_ERROR, amount)

    if not confirm_duplicate:
        same = db.scalars(
            sa.select(MFTransaction).where(
                MFTransaction.mutual_fund_id == holding.id,
                MFTransaction.manual.is_(True),
                MFTransaction.kind == "purchase",
                MFTransaction.txn_date == body.date,
            )
        ).all()
        if any(
            Decimal(str(t.amount)) == amount and Decimal(str(t.units)) == units for t in same
        ):
            raise BuyDuplicate(holding)

    sip_service.ensure_opening_transaction(db, holding)
    txn = MFTransaction(
        mutual_fund_id=holding.id, txn_date=body.date, kind="purchase", amount=amount,
        units=units, sip_id=None, manual=True,
    )  # fmt: skip
    db.add(txn)
    _set_totals(
        holding,
        Decimal(str(holding.units)) + units,
        Decimal(str(holding.invested_amount)) + amount,
    )
    db.flush()
    return BuyOutcome(transaction=txn, holding_name=duplicates.holding_name(holding), units_added=units)


def undo_mf_buy(db: Session, holding: MutualFund, txn_id: int) -> UndoBuyOutcome:
    """Remove one manual purchase from a locked, freshly read fund. Raises BuyNotFound (404) or
    ExitConflict (409). No commit."""
    txn = db.scalars(
        sa.select(MFTransaction).where(
            MFTransaction.id == txn_id,
            MFTransaction.mutual_fund_id == holding.id,
            MFTransaction.manual.is_(True),
            MFTransaction.kind == "purchase",
        )
    ).first()
    if txn is None:
        raise BuyNotFound()
    refusal = undo_refusal(holding, txn, last_sale_date(db, holding.id))
    if refusal is not None:
        raise refusal
    units = Decimal(str(txn.units))
    _set_totals(
        holding,
        Decimal(str(holding.units)) - units,
        Decimal(str(holding.invested_amount)) - Decimal(str(txn.amount)),
    )
    db.delete(txn)
    db.flush()
    return UndoBuyOutcome(holding_name=duplicates.holding_name(holding), units_removed=units)
