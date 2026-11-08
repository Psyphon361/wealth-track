"""Closing holdings: selling (all or part), settling a matured deposit or bond, and undo.

The maths is in small pure functions (`check_sale`, `sale_cost`, `fifo_cost`, `remaining_after`);
`record_sale`, `record_settlement` and `undo_exit` are the only writers. They never commit: the
router commits once, so a failure anywhere leaves nothing written.

A sale of everything keeps the holding's original quantity and invested amount and sets
`closed_on` (status "sold"); a partial sale reduces the holding. A mutual fund sale also writes a
`redemption` transaction (and, for a fund with no transactions yet, an opening purchase first) so
its XIRR stays on the transaction basis.
"""

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    HoldingExit,
    MFTransaction,
    MfSip,
    MutualFund,
    Other,
    RecurringDeposit,
    Stock,
)
from app.schemas.exits import (
    CASH_ACCOUNT_ERROR,
    CHARGES_TOO_HIGH_ERROR,
    EXIT_DATE_FUTURE_ERROR,
    SELL_DATE_BEFORE_PURCHASE_ERROR,
    SELL_PART_REFUSED_DESCRIPTION,
    SELL_PART_REFUSED_MESSAGE,
    SELL_QUANTITY_TOO_MANY_ERROR,
    SETTLE_DATE_BEFORE_MATURITY_ERROR,
    ExitSummary,
    SellBody,
    SettleBody,
    _Destination,
)
from app.services import analytics, duplicates, fundings, networth, valuation
from app.services import sip as sip_service

SELL_TYPES = ("stock", "bond", "mf", "gold", "other")
SETTLE_TYPES = ("fd", "rd", "bond")
EXIT_TYPES = ("fd", "rd", "bond", "stock", "mf", "gold", "other")

MODELS: dict[str, Any] = {
    "fd": FixedDeposit,
    "rd": RecurringDeposit,
    "bond": Bond,
    "stock": Stock,
    "mf": MutualFund,
    "gold": Gold,
    "other": Other,
}
# Attribute holding the quantity (shares, bond units, fund units, grams) of each sellable type.
QUANTITY_ATTR = {"stock": "quantity", "bond": "quantity", "mf": "units", "gold": "weight_grams"}
INVESTED_ATTR = {
    "bond": "invested_amount",
    "mf": "invested_amount",
    "gold": "invested_amount",
    "other": "invested_amount",
}
WHOLE_NUMBER_TYPES = ("stock", "bond")

_CENT = Decimal("0.01")
_UNITS = Decimal("0.001")
_NAV = Decimal("0.0001")
_ZERO = Decimal("0")
# Net units of a fund's transactions may differ from the holding's by this much (as in XIRR).
_UNITS_TOLERANCE = Decimal("0.01")


class ExitError(Exception):
    """One field is invalid; the router turns it into a 422 pointing at `loc`."""

    def __init__(self, loc: tuple[str, ...], message: str, value: Any = None):
        super().__init__(message)
        self.loc = loc
        self.message = message
        self.value = value


class ExitRefused(ExitError):
    """A partial sale the recorded cost can't support (422 with its own message and description)."""

    def __init__(self, loc: tuple[str, ...], value: Any = None):
        super().__init__(loc, SELL_PART_REFUSED_MESSAGE, value)
        self.description = SELL_PART_REFUSED_DESCRIPTION


class ExitConflict(Exception):
    """The holding is not in a state that allows this (409)."""

    def __init__(self, message: str, description: str):
        super().__init__(message)
        self.message = message
        self.description = description


# --- Pure maths ---------------------------------------------------------------------------------


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)


def units(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(_UNITS, rounding=ROUND_HALF_UP)


def gross_amount(quantity: Decimal, price: Decimal) -> Decimal:
    """Sale value before charges: quantity x price per unit, 2 dp."""
    return money(Decimal(str(quantity)) * Decimal(str(price)))


def net_amount(quantity: Decimal, price: Decimal, charges: Decimal) -> Decimal:
    """Money received: quantity x price less charges, 2 dp."""
    return gross_amount(quantity, price) - money(charges)


def proportional_cost(invested: Decimal, held: Decimal, sold: Decimal) -> Decimal:
    """The share of the invested amount that belongs to `sold` of `held` units, 2 dp."""
    if held <= 0:
        return _ZERO
    return money(Decimal(str(invested)) * Decimal(str(sold)) / Decimal(str(held)))


def _consume(lots: deque[list[Decimal]], quantity: Decimal) -> Decimal:
    """Take `quantity` units from the oldest lots; returns the cost of what was taken."""
    remaining = quantity
    cost = _ZERO
    while remaining > 0 and lots:
        lot = lots[0]
        if lot[0] <= remaining:
            remaining -= lot[0]
            cost += lot[1]
            lots.popleft()
        else:
            part = lot[1] * remaining / lot[0]
            cost += part
            lot[1] -= part
            lot[0] -= remaining
            remaining = _ZERO
    return cost


def net_units(txns: Iterable[Any]) -> Decimal:
    return sum(
        (
            Decimal(str(t.units)) if t.kind == "purchase" else -Decimal(str(t.units))
            for t in txns
        ),
        _ZERO,
    )


def fifo_cost(txns: Sequence[Any], quantity: Decimal) -> Decimal:
    """Cost of selling `quantity` units on top of the transactions: the oldest units first.

    Earlier redemptions consume the oldest purchases before this sale does. Raises ValueError when
    fewer units than `quantity` remain.
    """
    lots: deque[list[Decimal]] = deque()  # [units, cost]
    for t in networth.sorted_txns(txns):
        t_units = Decimal(str(t.units))
        if t.kind == "purchase":
            lots.append([t_units, abs(Decimal(str(t.amount)))])
        else:
            _consume(lots, t_units)
    left = sum((lot[0] for lot in lots), _ZERO)
    wanted = Decimal(str(quantity))
    if wanted > left + _UNITS_TOLERANCE:
        raise ValueError("not enough units")
    return money(_consume(lots, min(wanted, left)))


def sale_cost(
    slug: str,
    *,
    held: Decimal,
    invested: Decimal,
    quantity: Decimal | None,
    full: bool,
    txns: Sequence[Any] = (),
) -> Decimal:
    """Cost basis of what is sold. All of it: the invested amount. Part of a fund with matching
    transactions: FIFO. Anything else: the invested amount pro rata. Never more than invested."""
    invested = money(invested)
    if full or quantity is None:
        return invested
    if slug == "mf" and txns and abs(net_units(txns) - held) <= _UNITS_TOLERANCE:
        cost = fifo_cost(txns, quantity)
    else:
        cost = proportional_cost(invested, held, quantity)
    return min(cost, invested)


def remaining_after(
    slug: str, held: Decimal, invested: Decimal, quantity: Decimal, cost: Decimal
) -> tuple[Decimal, Decimal, Decimal | None]:
    """(quantity left, invested left, average NAV) after a partial sale. The average NAV is for
    funds only (invested / units, 4 dp); a stock keeps its average price."""
    left = Decimal(str(held)) - Decimal(str(quantity))
    left_invested = money(Decimal(str(invested)) - cost)
    avg_nav = None
    if slug == "mf" and left > 0:
        avg_nav = (left_invested / left).quantize(_NAV, rounding=ROUND_HALF_UP)
    return left, left_invested, avg_nav


_FUND_NAV_FLOOR = Decimal("0.00005")


def remainder_floor(slug: str, left: Decimal) -> Decimal:
    """Least invested amount a partly sold holding may keep. A fund needs avg NAV (invested /
    units) to round to at least 0.0001 at 4 dp, so 0.00005 per unit left, rounded up to the next
    paisa; anything else needs a paisa."""
    if slug == "mf":
        return max((_FUND_NAV_FLOOR * Decimal(str(left))).quantize(_CENT, rounding=ROUND_UP), _CENT)
    return _CENT


def check_remainder(
    slug: str, held: Decimal, invested: Decimal, quantity: Decimal, cost: Decimal
) -> None:
    """Refuse a PARTIAL sale whose cost leaves the remainder below the floor. A full sale never
    comes here. Raises ExitRefused."""
    left, left_invested, _ = remaining_after(slug, held, invested, quantity, cost)
    if left > 0 and left_invested < remainder_floor(slug, left):
        raise ExitRefused(("quantity",), quantity)


@dataclass(frozen=True)
class SalePlan:
    quantity: Decimal | None  # None for Other
    gross: Decimal
    charges: Decimal
    amount: Decimal  # money received: gross less charges
    full: bool


def check_sale(
    slug: str,
    *,
    held: Decimal | None,
    sale_date: date,
    start: date | None,
    today: date,
    quantity: Decimal | None,
    price: Decimal | None,
    amount: Decimal | None,
    charges: Decimal,
) -> SalePlan:
    """Validate one sale against the holding and work out its amounts. Raises ExitError."""
    if sale_date > today:
        raise ExitError(("date",), EXIT_DATE_FUTURE_ERROR, sale_date)
    if start is not None and sale_date < start:
        raise ExitError(("date",), SELL_DATE_BEFORE_PURCHASE_ERROR, sale_date)
    charges = money(charges)
    if slug == "other":
        if amount is None:
            raise ExitError(("amount",), "Required")
        gross, sold, full = money(amount), None, True
    else:
        if quantity is None:
            raise ExitError(("quantity",), "Required")
        if slug in WHOLE_NUMBER_TYPES and quantity != quantity.to_integral_value():
            raise ExitError(("quantity",), "Must be a whole number", quantity)
        if held is None or quantity > held:
            raise ExitError(("quantity",), SELL_QUANTITY_TOO_MANY_ERROR, quantity)
        if price is None:
            raise ExitError(("price",), "Required")
        gross, sold, full = gross_amount(quantity, price), quantity, quantity == held
    if gross <= 0:
        raise ExitError(("amount",) if slug == "other" else ("price",), "Must be greater than 0")
    if charges >= gross:
        raise ExitError(("charges",), CHARGES_TOO_HIGH_ERROR, charges)
    return SalePlan(sold, gross, charges, gross - charges, full)


# --- Holding state ------------------------------------------------------------------------------


def holding_status(slug: str, record: Any, today: date) -> str:
    """active, matured (deposits and bonds past maturity) or sold (closed_on set)."""
    if getattr(record, "closed_on", None) is not None:
        return "sold"
    if slug in ("fd", "rd"):
        return valuation._status(today, valuation._maturity(record))
    if slug == "bond":
        return valuation._status(today, record.maturity_date)
    return "active"


def start_date_of(slug: str, record: Any) -> date | None:
    return {
        "stock": lambda r: r.buy_date,
        "bond": lambda r: r.purchase_date,
        "mf": lambda r: r.purchase_date,
        "gold": lambda r: r.purchase_date,
        "other": lambda r: r.acquired_on,
    }[slug](record)


def _held_and_invested(slug: str, record: Any) -> tuple[Decimal | None, Decimal]:
    if slug == "stock":
        return Decimal(record.quantity), money(Decimal(record.quantity) * Decimal(record.avg_buy_price))
    if slug == "other":
        invested = record.invested_amount
        return None, money(invested) if invested is not None else _ZERO
    return Decimal(str(getattr(record, QUANTITY_ATTR[slug]))), money(record.invested_amount)


def _not_active(slug: str, record: Any, today: date) -> ExitConflict | None:
    status = holding_status(slug, record, today)
    if status == "sold":
        return ExitConflict(
            "Already sold",
            "This holding has been sold. Undo the sale first if it was a mistake.",
        )
    if status == "matured":
        return ExitConflict(
            "This bond has matured",
            "Record where the money went with Settle instead of selling.",
        )
    return None


# --- Exit rows ----------------------------------------------------------------------------------


def exit_summary(row: HoldingExit, reinvested: Decimal = _ZERO) -> dict[str, Any]:
    """The `exit` object on holding items (JSON-ready). `reinvested` is the money of this exit
    that "Paid from" put into holdings that still exist."""
    prev = row.prev_state or {}
    return ExitSummary(
        id=row.id,
        kind=row.kind,
        date=row.exit_date,
        quantity=row.quantity,
        amount=row.amount,
        cost=row.cost,
        charges=row.charges,
        destination=row.destination,
        cash_holding_id=row.cash_holding_id,
        new_holding_id=row.new_holding_id,
        new_asset_type=prev.get("new_asset_type"),
        reinvested=reinvested,
        left_in_account=fundings.left_in_account(row.cash_added, reinvested),
    ).model_dump(mode="json")


def exit_read(row: HoldingExit, reinvested: Decimal = _ZERO) -> dict[str, Any]:
    """Fields of the ExitRead response model."""
    prev = row.prev_state or {}
    return {
        "id": row.id,
        "asset_type": row.asset_type,
        "holding_id": row.holding_id,
        "kind": row.kind,
        "date": row.exit_date,
        "quantity": row.quantity,
        "amount": row.amount,
        "cost": row.cost,
        "charges": row.charges,
        "destination": row.destination,
        "cash_holding_id": row.cash_holding_id,
        "cash_added": row.cash_added,
        "new_holding_id": row.new_holding_id,
        "new_asset_type": prev.get("new_asset_type"),
        "created_at": row.created_at,
        "realised_gain": Decimal(str(row.amount)) - Decimal(str(row.cost)),
        "reinvested": reinvested,
        "left_in_account": fundings.left_in_account(row.cash_added, reinvested),
    }


def list_exits(db: Session, user_id: int, slug: str, holding_id: int) -> list[HoldingExit]:
    """A holding's exits, newest first."""
    return list(
        db.scalars(
            sa.select(HoldingExit)
            .where(
                HoldingExit.user_id == user_id,
                HoldingExit.asset_type == slug,
                HoldingExit.holding_id == holding_id,
            )
            .order_by(HoldingExit.id.desc())
        ).all()
    )


def latest_exit_id(db: Session, row: HoldingExit) -> int | None:
    return db.scalar(
        sa.select(sa.func.max(HoldingExit.id)).where(
            HoldingExit.user_id == row.user_id,
            HoldingExit.asset_type == row.asset_type,
            HoldingExit.holding_id == row.holding_id,
        )
    )


def fetch_exit_info(session: Session, user_id: int) -> dict[tuple[str, int], dict[str, Any]]:
    """{(type, holding id): {"exit": latest exit summary, "settled": a maturity exit exists}}."""
    rows = session.scalars(
        sa.select(HoldingExit).where(HoldingExit.user_id == user_id).order_by(HoldingExit.id)
    ).all()
    reinvested = fundings.reinvested_by_exit(session, user_id) if rows else {}
    info: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        entry = info.setdefault((row.asset_type, row.holding_id), {"exit": None, "settled": False})
        entry["exit"] = exit_summary(row, reinvested.get(row.id, _ZERO))
        if row.kind == "maturity":
            entry["settled"] = True
    return info


def maturity_amount_of(slug: str, item: Mapping[str, Any]) -> Decimal | None:
    """What a matured deposit or bond pays at maturity (the settle dialog's default amount)."""
    maturity = analytics._to_date(item.get("maturity_date"))
    if maturity is None or slug not in SETTLE_TYPES:
        return None
    amount, _rate, _approximate = analytics._maturity_amount(slug, item, maturity, {})
    return money(amount)


def apply_exit_info(
    groups: Iterable[Mapping[str, Any]], info: Mapping[tuple[str, int], Mapping[str, Any]]
) -> None:
    """Set `exit`, `settled` and `maturity_amount` on the items of valued groups, in place.

    `maturity_amount` is set only for matured, unsettled deposits and bonds.
    """
    for group in groups:
        slug = group["type"]
        for item in group["items"]:
            found = info.get((slug, item["id"]))
            if found is not None:
                item["exit"] = found["exit"]
                item["settled"] = found["settled"]
            if (
                slug in SETTLE_TYPES
                and item.get("status") == "matured"
                and not item.get("settled")
                and item.get("closed_on") is None
            ):
                amount = maturity_amount_of(slug, item)
                item["maturity_amount"] = float(amount) if amount is not None else None


def unsettled(groups: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Matured deposits and bonds with no maturity exit: {count, amount, items}."""
    items: list[dict[str, Any]] = []
    for group in groups:
        slug = group["type"]
        if slug not in SETTLE_TYPES:
            continue
        for item in group["items"]:
            if (
                item.get("status") != "matured"
                or item.get("settled")
                or item.get("closed_on") is not None
            ):
                continue
            maturity = analytics._to_date(item.get("maturity_date"))
            amount = maturity_amount_of(slug, item)
            if maturity is None or amount is None:
                continue
            items.append(
                {
                    "type": slug,
                    "id": item["id"],
                    "name": analytics._item_name(item),
                    "maturity_date": maturity,
                    "amount": amount,
                }
            )
    items.sort(key=lambda i: (i["maturity_date"], i["type"], i["id"]))
    return {
        "count": len(items),
        "amount": sum((i["amount"] for i in items), _ZERO),
        "items": items,
    }


# --- Writers ------------------------------------------------------------------------------------


@dataclass
class ExitOutcome:
    row: HoldingExit
    closed: bool
    holding_name: str
    remaining: Decimal | None = None
    cash_name: str | None = None
    sips_cancelled: int = 0
    prev: dict[str, Any] = field(default_factory=dict)


def _resolve_cash(db: Session, user_id: int, dest: _Destination) -> Cash | None:
    """The user's cash account a payout goes into; None unless kind is cash_existing."""
    if dest.kind != "cash_existing":
        return None
    cash = db.scalars(
        sa.select(Cash).where(Cash.id == dest.cash_id, Cash.user_id == user_id).with_for_update(of=Cash)
    ).first()
    if cash is None:
        raise ExitError(("destination", "cash_id"), CASH_ACCOUNT_ERROR, dest.cash_id)
    return cash


def _pay_into_cash(
    db: Session,
    user_id: int,
    dest: _Destination,
    cash: Cash | None,
    amount: Decimal,
    on_date: date,
    prev: dict[str, Any],
) -> Cash | None:
    """Add the money to an existing account or open a new savings account for it."""
    if dest.kind == "cash_existing":
        assert cash is not None
        prev["cash_balance"] = str(cash.balance)
        prev["cash_balance_date"] = cash.balance_date.isoformat()
        cash.balance = Decimal(str(cash.balance)) + amount
        cash.balance_date = max(cash.balance_date, on_date)
        prev["cash_date_set"] = cash.balance_date.isoformat()
        return cash
    if dest.kind == "cash_new":
        created = Cash(
            user_id=user_id,
            name=dest.cash_name,
            kind="savings",
            balance=amount,
            balance_date=on_date,
        )
        db.add(created)
        db.flush()
        prev["cash_created"] = True
        return created
    return None


def record_sale(
    db: Session, user_id: int, slug: str, holding: Any, body: SellBody, today: date
) -> ExitOutcome:
    """Sell all or part of a holding. Raises ExitConflict (409) or ExitError (422); no commit."""
    conflict = _not_active(slug, holding, today)
    if conflict is not None:
        raise conflict
    held, invested = _held_and_invested(slug, holding)
    plan = check_sale(
        slug,
        held=held,
        sale_date=body.date,
        start=start_date_of(slug, holding),
        today=today,
        quantity=body.quantity,
        price=body.price,
        amount=body.amount,
        charges=body.charges,
    )
    cash = _resolve_cash(db, user_id, body.destination)

    prev: dict[str, Any] = {}
    if plan.full:
        prev["full"] = True
    if slug in QUANTITY_ATTR:
        prev["quantity"] = str(getattr(holding, QUANTITY_ATTR[slug]))
    if slug in INVESTED_ATTR and getattr(holding, INVESTED_ATTR[slug]) is not None:
        prev["invested"] = str(getattr(holding, INVESTED_ATTR[slug]))
    if slug == "mf":
        prev["avg_nav"] = str(holding.avg_nav)

    txns: list[Any] = []
    if slug == "mf":
        txns = list(
            db.scalars(
                sa.select(MFTransaction)
                .where(MFTransaction.mutual_fund_id == holding.id)
                .order_by(MFTransaction.txn_date, MFTransaction.id)
            ).all()
        )
        if not txns:
            opening = sip_service.ensure_opening_transaction(db, holding)
            if opening is not None:
                txns = [opening]
    cost = sale_cost(
        slug, held=held or _ZERO, invested=invested, quantity=plan.quantity, full=plan.full,
        txns=txns,
    )  # fmt: skip
    if not plan.full:
        check_remainder(slug, held, invested, plan.quantity, cost)

    remaining = None
    sips_cancelled = 0
    if plan.full:
        holding.closed_on = body.date
    else:
        left, left_invested, avg_nav = remaining_after(slug, held, invested, plan.quantity, cost)
        remaining = left
        if slug in ("stock", "bond"):
            holding.quantity = int(left)
        elif slug == "mf":
            holding.units = units(left)
        else:
            holding.weight_grams = units(left)
        if slug in INVESTED_ATTR:
            setattr(holding, INVESTED_ATTR[slug], left_invested)
        if avg_nav is not None:
            holding.avg_nav = avg_nav

    redemption = None
    if slug == "mf":
        redemption = MFTransaction(
            mutual_fund_id=holding.id,
            txn_date=body.date,
            kind="redemption",
            amount=plan.amount,
            units=plan.quantity,
        )
        db.add(redemption)
        if plan.full:
            running = db.scalars(
                sa.select(MfSip).where(
                    MfSip.mutual_fund_id == holding.id,
                    MfSip.user_id == user_id,
                    MfSip.status.in_([sip_service.ACTIVE, sip_service.PAUSED]),
                )
            ).all()
            prev["stopped_sips"] = [{"id": s.id, "status": s.status} for s in running]
            for sip in running:
                sip.status = sip_service.STOPPED
            sips_cancelled = len(running)

    paid_into = _pay_into_cash(db, user_id, body.destination, cash, plan.amount, body.date, prev)
    row = HoldingExit(
        user_id=user_id,
        asset_type=slug,
        holding_id=holding.id,
        kind="sale",
        exit_date=body.date,
        quantity=plan.quantity,
        amount=plan.amount,
        cost=cost,
        charges=plan.charges,
        destination="cash" if paid_into is not None else "none",
        cash_holding_id=paid_into.id if paid_into is not None else None,
        cash_added=plan.amount if paid_into is not None else None,
        mf_transaction_id=None,
        prev_state=prev,
    )
    db.add(row)
    db.flush()
    if redemption is not None:
        row.mf_transaction_id = redemption.id
    return ExitOutcome(
        row=row,
        closed=plan.full,
        holding_name=duplicates.holding_name(holding),
        remaining=remaining,
        cash_name=paid_into.name if paid_into is not None else None,
        sips_cancelled=sips_cancelled,
        prev=prev,
    )


def record_settlement(
    db: Session, user_id: int, slug: str, holding: Any, item: Mapping[str, Any], body: SettleBody,
    today: date,
) -> ExitOutcome:  # fmt: skip
    """Record where a matured deposit's or bond's money went. No commit.

    `item` is the holding's valued grid item (status, maturity date, invested).
    """
    name = duplicates.holding_name(holding)
    if getattr(holding, "closed_on", None) is not None:
        raise ExitConflict(
            "Already sold", "This bond was sold before it matured. Undo the sale first."
        )
    if item.get("status") != "matured":
        maturity = analytics._to_date(item.get("maturity_date"))
        when = f" on {maturity.day} {maturity:%b %Y}" if maturity else ""
        raise ExitConflict("Not matured yet", f"{name} matures{when}.")
    already = db.scalar(
        sa.select(HoldingExit.id).where(
            HoldingExit.asset_type == slug,
            HoldingExit.holding_id == holding.id,
            HoldingExit.kind == "maturity",
        )
    )
    if already is not None:
        raise ExitConflict(
            "Already settled", "Undo the settlement first if you need to change it."
        )

    maturity = analytics._to_date(item.get("maturity_date"))
    settle_date = body.date or maturity
    if settle_date > today:
        raise ExitError(("date",), EXIT_DATE_FUTURE_ERROR, settle_date)
    if settle_date < maturity:
        raise ExitError(("date",), SETTLE_DATE_BEFORE_MATURITY_ERROR, settle_date)
    amount = money(body.amount) if body.amount is not None else maturity_amount_of(slug, item)
    dest = body.destination
    cash = _resolve_cash(db, user_id, dest)

    prev: dict[str, Any] = {}
    paid_into = _pay_into_cash(db, user_id, dest, cash, amount, settle_date, prev)
    row = HoldingExit(
        user_id=user_id,
        asset_type=slug,
        holding_id=holding.id,
        kind="maturity",
        exit_date=settle_date,
        quantity=None,
        amount=amount,
        cost=money(item.get("invested") or 0),
        charges=_ZERO,
        destination="cash" if paid_into else "none",
        cash_holding_id=paid_into.id if paid_into is not None else None,
        cash_added=amount if paid_into is not None else None,
        prev_state=prev,
    )
    db.add(row)
    db.flush()
    return ExitOutcome(
        row=row,
        closed=True,
        holding_name=name,
        cash_name=paid_into.name if paid_into is not None else None,
        prev=prev,
    )


@dataclass
class UndoOutcome:
    kind: str
    holding_name: str
    cash_name: str | None = None
    cash_returned: Decimal | None = None
    cash_added: Decimal | None = None  # what the exit had added to the account
    sips_paused: int = 0
    cash_account_kept: str | None = None  # a new account the sale created


def _was_full_sale(row: HoldingExit, holding: Any) -> bool:
    """True when the sale closed the holding. Rows made before `full` was stored fall back to the
    holding being closed on the sale's date."""
    prev = row.prev_state or {}
    if "full" in prev:
        return bool(prev["full"])
    closed_on = getattr(holding, "closed_on", None)
    return closed_on is not None and closed_on == row.exit_date


def undo_exit(db: Session, row: HoldingExit, holding: Any) -> UndoOutcome:
    """Reverse the exit: restore the holding, take the money back out of the cash account, delete
    the redemption transaction. Does not delete a cash account the exit created. The caller checked this is the holding's latest exit. No commit."""
    prev = row.prev_state or {}
    slug = row.asset_type
    out = UndoOutcome(kind=row.kind, holding_name=duplicates.holding_name(holding))

    if row.kind == "sale":
        if _was_full_sale(row, holding):
            holding.closed_on = None  # a full sale never reduced the quantity
        elif slug in QUANTITY_ATTR and row.quantity is not None:
            # Add back what was sold instead of restoring a snapshot, so anything that changed
            # since (a SIP instalment, an edit) is kept.
            attr = QUANTITY_ATTR[slug]
            sold = Decimal(str(row.quantity))
            now_held = Decimal(str(getattr(holding, attr)))
            if slug in WHOLE_NUMBER_TYPES:
                setattr(holding, attr, int(now_held + sold))
            else:
                setattr(holding, attr, units(now_held + sold))
            invested_attr = INVESTED_ATTR.get(slug)
            if invested_attr is not None and getattr(holding, invested_attr) is not None:
                restored = money(Decimal(str(getattr(holding, invested_attr))) + Decimal(str(row.cost)))
                setattr(holding, invested_attr, restored)
                if slug == "mf":
                    total_units = Decimal(str(holding.units))
                    if total_units > _ZERO:
                        holding.avg_nav = (restored / total_units).quantize(
                            _NAV, rounding=ROUND_HALF_UP
                        )
        for entry in prev.get("stopped_sips", []):
            sip = db.get(MfSip, entry["id"])
            if sip is not None and sip.status == sip_service.STOPPED:
                # Paused, not running: missed instalments are not backfilled; the user resumes it.
                sip.status = sip_service.PAUSED
                out.sips_paused += 1
        if row.mf_transaction_id is not None:
            db.execute(sa.delete(MFTransaction).where(MFTransaction.id == row.mf_transaction_id))

    if row.cash_holding_id is not None and row.cash_added is not None:
        cash = db.scalars(
            sa.select(Cash)
            .where(Cash.id == row.cash_holding_id, Cash.user_id == row.user_id)
            .with_for_update(of=Cash)
        ).first()
        if cash is not None:
            balance_before = Decimal(str(cash.balance))
            added = Decimal(str(row.cash_added))
            taken = max(min(balance_before, added), _ZERO)
            cash.balance = balance_before - taken
            if (
                prev.get("cash_balance_date")
                and prev.get("cash_date_set") == cash.balance_date.isoformat()
            ):
                cash.balance_date = date.fromisoformat(prev["cash_balance_date"])
            out.cash_name = cash.name
            out.cash_returned = taken  # what was really taken out, never more than the account held
            out.cash_added = added
            if prev.get("cash_created"):
                out.cash_account_kept = cash.name

    db.delete(row)
    return out
