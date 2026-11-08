from datetime import date
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.mf_master import MFMaster
from app.models.mf_sip import MfSip, MfSipSkip
from app.models.mf_transaction import MFTransaction
from app.models.mutual_fund import MutualFund
from app.models.user import User
from app.schemas.messages import Outcome
from app.schemas.sip import (
    SIP_END_BEFORE_START_ERROR,
    SIP_HOLDING_MISMATCH_ERROR,
    SIP_HOLDING_SOLD_ERROR,
    SIP_INACTIVE_SCHEME_ERROR,
    SIP_NO_INSTALMENT_ERROR,
    SIP_SKIP_NOT_UPCOMING_ERROR,
    SipCreate,
    SipRead,
    SipResult,
    SipSkipBody,
    SipUpdate,
)
from app.services import amfi
from app.services import sip as sip_service

router = APIRouter(prefix="/sips", tags=["sips"])

STATUS_ORDER = {sip_service.ACTIVE: 0, sip_service.PAUSED: 1, sip_service.STOPPED: 2}


def _invalid(field: str, message: str, value: Any) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", field), "msg": message, "input": str(value)}]
    )


def _conflict(message: str, description: str) -> HTTPException:
    return HTTPException(status_code=409, detail={"message": message, "description": description})


def _get_or_404(db: Session, sip_id: int, user: User) -> MfSip:
    sip = db.scalars(
        sa.select(MfSip).where(MfSip.id == sip_id, MfSip.user_id == user.id)
    ).first()
    if sip is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "SIP not found",
                "description": "It may have been deleted already.",
            },
        )
    return sip


def _fund_names(db: Session, scheme_codes: set[int]) -> dict[int, str]:
    if not scheme_codes:
        return {}
    rows = db.execute(
        sa.select(MFMaster.scheme_code, MFMaster.name).where(MFMaster.scheme_code.in_(scheme_codes))
    ).all()
    return {code: name for code, name in rows}


def _reads(db: Session, sips: list[MfSip], today: date) -> list[dict[str, Any]]:
    """SIP read models, with three queries in total however many SIPs there are."""
    ids = [s.id for s in sips]
    stats = sip_service.instalment_stats(db, ids)
    skips = sip_service.upcoming_skips(db, ids, today)
    names = _fund_names(db, {s.scheme_code for s in sips})
    out = []
    for sip in sips:
        count, invested = stats.get(sip.id, (0, 0))
        out.append(
            {
                "id": sip.id,
                "mutual_fund_id": sip.mutual_fund_id,
                "scheme_code": sip.scheme_code,
                "fund_name": names.get(sip.scheme_code, ""),
                "platform": sip.platform,
                "amount": sip.amount,
                "day_of_month": sip.day_of_month,
                "start_date": sip.start_date,
                "end_date": sip.end_date,
                "status": sip.status,
                "next_date": sip_service.next_date_of(sip, today),
                "skipped_dates": skips.get(sip.id, []),
                "instalments_added": count,
                "invested_via_sip": invested,
            }
        )
    return out


def _result(db: Session, sip: MfSip, today: date, message: str, description: str) -> SipResult:
    return SipResult(**_reads(db, [sip], today)[0], message=message, description=description)


def _fund_name(db: Session, sip: MfSip) -> str:
    return _fund_names(db, {sip.scheme_code}).get(sip.scheme_code, "")


@router.post("", response_model=SipResult, status_code=201)
def create_sip(
    body: SipCreate,
    confirm_duplicate: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    scheme = amfi.require_scheme(db, body.scheme_code)
    if not scheme.is_active:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "scheme_code"),
                    "msg": SIP_INACTIVE_SCHEME_ERROR,
                    "input": body.scheme_code,
                }
            ]
        )

    holding_id = None
    if body.mutual_fund_id is not None:
        holding = db.scalars(
            sa.select(MutualFund).where(
                MutualFund.id == body.mutual_fund_id, MutualFund.user_id == user.id
            )
        ).first()
        if holding is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Holding not found",
                    "description": "It may have been deleted, or it belongs to another account.",
                },
            )
        if holding.scheme_code != body.scheme_code:
            raise _invalid("mutual_fund_id", SIP_HOLDING_MISMATCH_ERROR, body.mutual_fund_id)
        if holding.closed_on is not None:
            raise _invalid("mutual_fund_id", SIP_HOLDING_SOLD_ERROR, body.mutual_fund_id)
        holding_id = holding.id
    else:
        matches = db.scalars(
            sa.select(MutualFund.id).where(
                MutualFund.user_id == user.id,
                MutualFund.scheme_code == body.scheme_code,
                MutualFund.closed_on.is_(None),  # a sold holding never takes units
                sa.func.lower(sa.func.trim(MutualFund.platform)) == body.platform.lower(),
            )
        ).all()
        if len(matches) == 1:
            holding_id = matches[0]

    schedule = sip_service.schedule_text(body.amount, body.day_of_month)
    if not confirm_duplicate:
        existing = db.scalars(
            sa.select(MfSip).where(
                MfSip.user_id == user.id,
                MfSip.scheme_code == body.scheme_code,
                MfSip.day_of_month == body.day_of_month,
                MfSip.amount == body.amount,
                MfSip.status == sip_service.ACTIVE,
            )
        ).all()
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "message": "This looks like a SIP you already have",
                    "description": f"{scheme.name} · {schedule} is already running.",
                    "duplicates": [{"id": s.id, "name": scheme.name} for s in existing],
                },
            )

    today = sip_service.today_ist()
    first = sip_service.first_due_on_or_after(
        body.day_of_month, body.start_date if body.include_past else max(body.start_date, today)
    )
    sip = MfSip(
        user_id=user.id,
        mutual_fund_id=holding_id,
        scheme_code=body.scheme_code,
        platform=body.platform,
        amount=body.amount,
        day_of_month=body.day_of_month,
        start_date=body.start_date,
        post_from=first,
        status=sip_service.ACTIVE,
    )
    db.add(sip)
    db.commit()
    added = sip_service.post_due(db, today, [sip.id]).get(sip.id, 0)
    db.refresh(sip)
    if added:
        word = "instalment" if added == 1 else "instalments"
        message = f"SIP started · {added} {word} added"
    else:
        message = "SIP started"
    return _result(db, sip, today, message, f"{scheme.name} · {schedule}")


@router.get("", response_model=list[SipRead])
def list_sips(
    mutual_fund_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    statement = sa.select(MfSip).where(MfSip.user_id == user.id)
    if mutual_fund_id is not None:
        statement = statement.where(MfSip.mutual_fund_id == mutual_fund_id)
    sips = sorted(db.scalars(statement).all(), key=lambda s: (STATUS_ORDER[s.status], s.id))
    return _reads(db, sips, sip_service.today_ist())


@router.put("/{sip_id}", response_model=SipResult)
def update_sip(
    sip_id: int,
    body: SipUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    sip = _get_or_404(db, sip_id, user)
    if sip.status == sip_service.STOPPED:
        raise _conflict("SIP is cancelled", "A cancelled SIP can't be changed. Start a new one.")
    if body.end_date is not None and body.end_date < sip.start_date:
        raise _invalid("end_date", SIP_END_BEFORE_START_ERROR, body.end_date)
    today = sip_service.today_ist()
    if body.day_of_month != sip.day_of_month:
        sip.post_from = sip_service.next_due(
            body.day_of_month, today, sip.post_from, None, sip.last_posted_on
        )
        for skip in db.scalars(
            sa.select(MfSipSkip).where(MfSipSkip.sip_id == sip.id, MfSipSkip.due_date >= today)
        ).all():
            if skip.due_date.day != body.day_of_month:
                db.delete(skip)
        sip.day_of_month = body.day_of_month
    sip.amount = body.amount
    sip.end_date = body.end_date
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, today, "SIP updated",
        f"{_fund_name(db, sip)} · {sip_service.schedule_text(sip.amount, sip.day_of_month)}",
    )  # fmt: skip


@router.post("/{sip_id}/pause", response_model=SipResult)
def pause_sip(
    sip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    sip = _get_or_404(db, sip_id, user)
    if sip.status != sip_service.ACTIVE:
        raise _conflict("SIP isn't running", "Only a running SIP can be paused.")
    sip.status = sip_service.PAUSED
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, sip_service.today_ist(), "SIP paused",
        f"{_fund_name(db, sip)} · no instalments are added until you resume it",
    )  # fmt: skip


@router.post("/{sip_id}/resume", response_model=SipResult)
def resume_sip(
    sip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    sip = _get_or_404(db, sip_id, user)
    if sip.status != sip_service.PAUSED:
        raise _conflict("SIP isn't paused", "Only a paused SIP can be resumed.")
    today = sip_service.today_ist()
    # Instalments missed while paused are not added: restart from the next due date.
    sip.post_from = (
        sip_service.next_due(sip.day_of_month, today, today, sip.end_date, sip.last_posted_on)
        or today
    )
    sip.status = sip_service.ACTIVE
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, today, "SIP resumed",
        f"{_fund_name(db, sip)} · {sip_service.schedule_text(sip.amount, sip.day_of_month)}",
    )  # fmt: skip


@router.post("/{sip_id}/stop", response_model=SipResult)
def stop_sip(
    sip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    sip = _get_or_404(db, sip_id, user)
    if sip.status == sip_service.STOPPED:
        raise _conflict("SIP is already cancelled", "It has no more instalments to add.")
    sip.status = sip_service.STOPPED
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, sip_service.today_ist(), "SIP cancelled",
        f"{_fund_name(db, sip)} · instalments already added stay in your holding",
    )  # fmt: skip


def _label(due: date) -> str:
    return f"{due.day} {due.strftime('%b %Y')}"


@router.post("/{sip_id}/skip", response_model=SipResult)
def skip_instalment(
    sip_id: int,
    body: SipSkipBody | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    sip = _get_or_404(db, sip_id, user)
    if sip.status != sip_service.ACTIVE:
        raise _conflict("SIP isn't running", "Only a running SIP has instalments to skip.")
    today = sip_service.today_ist()
    requested = body.due_date if body is not None else None
    due = requested or sip_service.next_date_of(sip, today)
    if due is None:
        raise _invalid("due_date", SIP_NO_INSTALMENT_ERROR, "")
    upcoming = (
        due >= today
        and due.day == sip.day_of_month
        and due >= sip.post_from
        and (sip.last_posted_on is None or due > sip.last_posted_on)
        and (sip.end_date is None or due <= sip.end_date)
    )
    if not upcoming:
        raise _invalid("due_date", SIP_SKIP_NOT_UPCOMING_ERROR, due)
    if db.scalar(
        sa.select(MfSipSkip.id).where(MfSipSkip.sip_id == sip.id, MfSipSkip.due_date == due)
    ):
        raise _conflict("Instalment already skipped", f"{_label(due)} is already skipped.")
    db.add(MfSipSkip(sip_id=sip.id, due_date=due))
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, today, "Instalment skipped", f"{_fund_name(db, sip)} · {_label(due)}"
    )


@router.delete("/{sip_id}/skip/{due_date}", response_model=SipResult)
def unskip_instalment(
    sip_id: int,
    due_date: date,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    sip = _get_or_404(db, sip_id, user)
    skip = db.scalars(
        sa.select(MfSipSkip).where(MfSipSkip.sip_id == sip.id, MfSipSkip.due_date == due_date)
    ).first()
    if skip is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Skip not found",
                "description": "That instalment isn't skipped.",
            },
        )
    today = sip_service.today_ist()
    if due_date < today:
        raise _invalid("due_date", SIP_SKIP_NOT_UPCOMING_ERROR, due_date)
    db.delete(skip)
    db.commit()
    db.refresh(sip)
    return _result(
        db, sip, today, "Skip removed", f"{_fund_name(db, sip)} · {_label(due_date)} will be added"
    )


@router.delete("/{sip_id}", response_model=Outcome)
def delete_sip(
    sip_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
):
    sip = _get_or_404(db, sip_id, user)
    name = _fund_name(db, sip)
    # Instalments already added stay; they just stop pointing at the SIP.
    db.execute(
        sa.update(MFTransaction).where(MFTransaction.sip_id == sip.id).values(sip_id=None)
    )
    db.execute(sa.delete(MfSipSkip).where(MfSipSkip.sip_id == sip.id))
    db.delete(sip)
    db.commit()
    return Outcome(
        message="SIP deleted", description=f"{name} · instalments already added stay in your holding"
    )
