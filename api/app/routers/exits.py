"""Closing holdings: sell, settle a maturity, list a holding's exits, undo (SPEC §10)."""

from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import HoldingExit
from app.models.user import User
from app.routers.portfolio import load_holding
from app.schemas.exits import ExitRead, ExitResult, SellBody, SettleBody
from app.schemas.messages import Outcome
from app.services import exits as exits_service
from app.services import fundings as fundings_service
from app.services import sip as sip_service
from app.services.exits import EXIT_TYPES, MODELS, SELL_TYPES, SETTLE_TYPES, ExitConflict, ExitError

router = APIRouter(tags=["exits"])

_NOUNS = {"stock": "Stock", "bond": "Bond", "mf": "Fund", "gold": "Gold", "other": "Holding"}


def _not_found(message: str = "Holding not found") -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "message": message,
            "description": "It may have been deleted, or it belongs to another account.",
        },
    )


def _invalid(error: ExitError) -> RequestValidationError:
    return RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", *error.loc),
                "msg": error.message,
                "input": "" if error.value is None else str(error.value),
            }
        ]
    )


def _conflict(error: ExitConflict) -> HTTPException:
    return HTTPException(
        status_code=409, detail={"message": error.message, "description": error.description}
    )


def _get_holding(db: Session, slug: str, item_id: int, user: User, *, lock: bool = False) -> Any:
    statement = sa.select(MODELS[slug]).where(
        MODELS[slug].id == item_id, MODELS[slug].user_id == user.id
    )
    if lock:
        statement = statement.with_for_update(of=MODELS[slug])  # not the joined master (outer join)
    holding = db.scalars(statement).first()
    if holding is None:
        raise _not_found()
    return holding


def _quantity_text(slug: str, quantity: Decimal) -> str:
    text = f"{quantity:f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return f"{text} g" if slug == "gold" else text


def _result(outcome: exits_service.ExitOutcome, message: str, description: str) -> ExitResult:
    return ExitResult(
        **exits_service.exit_read(outcome.row),
        message=message,
        description=description,
        closed=outcome.closed,
        remaining=outcome.remaining,
        cash_name=outcome.cash_name,
        sips_cancelled=outcome.sips_cancelled,
    )


def _gain_text(row: HoldingExit) -> str | None:
    gain = Decimal(str(row.amount)) - Decimal(str(row.cost))
    if Decimal(str(row.cost)) <= 0 or gain == 0:
        return None
    word = "gain" if gain > 0 else "loss"
    return f"{word} {sip_service.format_inr(abs(gain))}"


@router.post("/holdings/{slug}/{item_id}/sell", response_model=ExitResult, status_code=201)
def sell_holding(
    slug: str,
    item_id: int,
    body: SellBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if slug not in SELL_TYPES:
        raise _not_found("Can't be sold")
    holding = _get_holding(db, slug, item_id, user, lock=True)
    try:
        outcome = exits_service.record_sale(
            db, user.id, slug, holding, body, sip_service.today_ist()
        )
    except ExitConflict as error:
        db.rollback()
        raise _conflict(error) from None
    except ExitError as error:
        db.rollback()
        raise _invalid(error) from None
    db.commit()
    db.refresh(outcome.row)

    row = outcome.row
    noun = _NOUNS[slug]
    if slug == "gold":
        noun = holding.metal.capitalize()
    message = f"{noun} sold" if outcome.closed else f"Part of {noun.lower()} sold"
    parts = [outcome.holding_name]
    money = sip_service.format_inr(row.amount)
    if slug == "other":
        parts.append(f"sold for {money}")
    else:
        parts.append(f"{_quantity_text(slug, Decimal(str(row.quantity)))} sold for {money}")
    gain = _gain_text(row)
    if gain:
        parts.append(gain)
    if outcome.cash_name:
        parts.append(f"added to {outcome.cash_name}")
    if outcome.sips_cancelled:
        parts.append("SIP cancelled" if outcome.sips_cancelled == 1 else "SIPs cancelled")
    return _result(outcome, message, " · ".join(parts))


@router.post("/holdings/{slug}/{item_id}/settle", response_model=ExitResult, status_code=201)
def settle_holding(
    slug: str,
    item_id: int,
    body: SettleBody,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if slug not in SETTLE_TYPES:
        raise _not_found("Can't be settled")
    _get_holding(db, slug, item_id, user, lock=True)  # serialises with sell and other settles
    loaded = load_holding(db, slug, user.id, item_id)
    if loaded is None:
        raise _not_found()
    holding, item = loaded
    try:
        outcome = exits_service.record_settlement(
            db, user.id, slug, holding, item, body, sip_service.today_ist()
        )
        db.commit()
    except ExitConflict as error:
        db.rollback()
        raise _conflict(error) from None
    except ExitError as error:
        db.rollback()
        raise _invalid(error) from None
    except IntegrityError:
        db.rollback()  # two requests settled the same holding at once
        raise _conflict(
            ExitConflict("Already settled", "Undo the settlement first if you need to change it.")
        ) from None
    db.refresh(outcome.row)

    row = outcome.row
    money = sip_service.format_inr(row.amount)
    if outcome.cash_name:
        tail = f"{money} added to {outcome.cash_name}"
    else:
        tail = f"{money} received"
    return _result(outcome, "Maturity recorded", f"{outcome.holding_name} · {tail}")


@router.get("/holdings/{slug}/{item_id}/exits", response_model=list[ExitRead])
def list_exits(
    slug: str,
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Every sale or settlement of one holding, newest first."""
    if slug not in EXIT_TYPES:
        raise _not_found()
    _get_holding(db, slug, item_id, user)
    rows = exits_service.list_exits(db, user.id, slug, item_id)
    reinvested = fundings_service.reinvested_by_exit(db, user.id, [r.id for r in rows])
    return [exits_service.exit_read(r, reinvested.get(r.id, Decimal("0"))) for r in rows]


@router.delete("/exits/{exit_id}", response_model=Outcome)
def undo_exit(
    exit_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    """Undo a holding's latest sale or settlement."""
    row = db.scalars(
        sa.select(HoldingExit)
        .where(HoldingExit.id == exit_id, HoldingExit.user_id == user.id)
        .with_for_update()  # serialises with a reinvest from this exit (fundings.plan)
    ).first()
    if row is None:
        raise _not_found("Record not found")
    holding = db.scalars(
        sa.select(MODELS[row.asset_type])
        .where(MODELS[row.asset_type].id == row.holding_id, MODELS[row.asset_type].user_id == user.id)
        .with_for_update(of=MODELS[row.asset_type])
    ).first()
    if holding is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Holding not found",
                "description": "It was deleted. Restore it from Recently deleted, then undo.",
            },
        )
    if exits_service.latest_exit_id(db, row) != row.id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Undo the latest one first",
                "description": "A later sale of this holding was recorded after this one.",
            },
        )
    if fundings_service.reinvested_by_exit(db, user.id, [row.id]).get(row.id):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Some of this money was reinvested",
                "description": "Delete the holdings paid from it first, then undo.",
            },
        )
    outcome = exits_service.undo_exit(db, row, holding)
    db.commit()

    what = "Sale undone" if outcome.kind == "sale" else "Settlement undone"
    sentences = [f"{outcome.holding_name} is back in your portfolio."]
    if outcome.cash_name and outcome.cash_returned is not None:
        sentences.append(
            f"{sip_service.format_inr(outcome.cash_returned)} was taken out of {outcome.cash_name}."
        )
    if outcome.cash_account_kept:
        sentences.append(
            f"The account {outcome.cash_account_kept} was kept; delete it yourself if you don't want it."
        )
    if outcome.sips_paused:
        sentences.append("Its SIP was left paused; resume it if you still want it.")
    return Outcome(message=what, description=" ".join(sentences))
