"""Buy more for mutual funds: add units to a fund, and undo such a buy."""

import sqlalchemy as sa
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import MutualFund
from app.models.user import User
from app.routers.exits import _conflict, _invalid, _not_found
from app.schemas.buys import (
    BUY_DONE_MESSAGE,
    BUY_DUPLICATE_MESSAGE,
    BUY_NOT_MF_MESSAGE,
    BUY_UNDONE_MESSAGE,
    BuyBody,
    BuyResult,
)
from app.schemas.messages import Outcome
from app.services import buys as buys_service
from app.services import duplicates
from app.services import sip as sip_service
from app.services.exits import ExitConflict, ExitError

router = APIRouter(tags=["buys"])


def _locked_fund(db: Session, item_id: int, user: User) -> MutualFund:
    """The user's fund, row-locked and re-read so a sale or buy in flight is seen."""
    holding = db.scalars(
        sa.select(MutualFund)
        .where(MutualFund.id == item_id, MutualFund.user_id == user.id)
        .with_for_update(of=MutualFund)
        .execution_options(populate_existing=True)
    ).first()
    if holding is None:
        raise _not_found()
    return holding


@router.post("/holdings/{slug}/{item_id}/buy", response_model=BuyResult, status_code=201)
def buy_more(
    slug: str,
    item_id: int,
    body: BuyBody,
    confirm_duplicate: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if slug != "mf":
        raise _not_found(BUY_NOT_MF_MESSAGE)
    holding = _locked_fund(db, item_id, user)
    try:
        outcome = buys_service.record_mf_buy(
            db, holding, body, sip_service.today_ist(), confirm_duplicate
        )
    except buys_service.BuyDuplicate:
        db.rollback()
        name = duplicates.holding_name(holding)
        when = duplicates.format_date(body.date)
        return JSONResponse(
            status_code=409,
            content={
                "message": BUY_DUPLICATE_MESSAGE,
                "description": (
                    f"{name} · {sip_service.format_inr(body.amount)} on {when} is already recorded."
                ),
                "duplicates": [{"id": holding.id, "name": name}],
            },
        )
    except ExitConflict as error:
        db.rollback()
        raise _conflict(error) from None
    except ExitError as error:
        db.rollback()
        raise _invalid(error) from None
    db.commit()
    db.refresh(holding)

    txn = outcome.transaction
    units_text = duplicates._number(outcome.units_added)
    return BuyResult(
        message=BUY_DONE_MESSAGE,
        description=(
            f"{outcome.holding_name} · {units_text} units for {sip_service.format_inr(txn.amount)}"
        ),
        transaction_id=txn.id,
        units_added=outcome.units_added,
        units=holding.units,
        invested_amount=holding.invested_amount,
        avg_nav=holding.avg_nav,
    )


@router.delete("/holdings/{slug}/{item_id}/buys/{txn_id}", response_model=Outcome)
def undo_buy(
    slug: str,
    item_id: int,
    txn_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Undo a purchase added with Buy more."""
    if slug != "mf":
        raise _not_found(BUY_NOT_MF_MESSAGE)
    holding = _locked_fund(db, item_id, user)
    try:
        outcome = buys_service.undo_mf_buy(db, holding, txn_id)
    except buys_service.BuyNotFound:
        db.rollback()
        raise _not_found("Record not found") from None
    except ExitConflict as error:
        db.rollback()
        raise _conflict(error) from None
    db.commit()
    return Outcome(
        message=BUY_UNDONE_MESSAGE,
        description=(
            f"{outcome.holding_name} · {duplicates._number(outcome.units_removed)} units removed."
        ),
    )
