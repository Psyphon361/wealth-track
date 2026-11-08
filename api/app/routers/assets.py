from datetime import date
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.db import Base, get_db
from app.deps import current_user
from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    HoldingExit,
    MutualFund,
    Nps,
    Other,
    Pf,
    RecurringDeposit,
    Stock,
    User,
)
from app.schemas.assets import (
    HOLDING_CLOSED_DESCRIPTION,
    HOLDING_CLOSED_MESSAGE,
    SOLD_IN_PART_ERROR,
    SOLD_IN_PART_FIELDS,
)
from app.schemas.fundings import PaidFromBody
from app.schemas.messages import Outcome
from app.services import amfi, bond_master, duplicates, fd_issuers, fundings, nps, stock_master
from app.services import sip as sip_service

router = APIRouter(prefix="/assets")

# type slug -> (model, create schema, read schema)
REGISTRY = {
    "fd": (FixedDeposit, schemas.FixedDepositCreate, schemas.FixedDepositRead),
    "rd": (RecurringDeposit, schemas.RecurringDepositCreate, schemas.RecurringDepositRead),
    "stock": (Stock, schemas.StockCreate, schemas.StockRead),
    "bond": (Bond, schemas.BondCreate, schemas.BondRead),
    "mf": (MutualFund, schemas.MutualFundCreate, schemas.MutualFundRead),
    "nps": (Nps, schemas.NpsCreate, schemas.NpsRead),
    "gold": (Gold, schemas.GoldCreate, schemas.GoldRead),
    "cash": (Cash, schemas.CashCreate, schemas.CashRead),
    "pf": (Pf, schemas.PfCreate, schemas.PfRead),
    "other": (Other, schemas.OtherCreate, schemas.OtherRead),
}


ASSET_LABELS = {
    "fd": "Fixed deposit",
    "rd": "Recurring deposit",
    "stock": "Stock",
    "bond": "Bond",
    "mf": "Mutual fund",
    "nps": "NPS",
    "gold": "Gold & Silver",
    "cash": "Cash & Savings",
    "pf": "EPF & PPF",
    "other": "Other",
}


def _get_or_404(db: Session, model: type[Base], item_id: int, user_id: int):
    obj = db.scalars(select(model).where(model.id == item_id, model.user_id == user_id)).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _changed(stored, new) -> bool:
    """True when a submitted value differs from the stored one (numbers compared by value)."""
    if stored is None or new is None:
        return stored is not new
    if isinstance(stored, date):
        return stored != new
    if isinstance(stored, str) or isinstance(new, str):
        return str(stored).strip().casefold() != str(new).strip().casefold()
    return Decimal(str(stored)) != Decimal(str(new))


def _holding_name(obj) -> str:
    """Display name of a holding for user-facing messages."""
    if hasattr(obj, "bank"):
        return f"{obj.bank} · {obj.label}" if obj.label else obj.bank
    if hasattr(obj, "scheme_name"):
        return obj.scheme_name
    return obj.name


def _build_router(slug: str, model, create, read) -> APIRouter:
    sub = APIRouter(prefix=f"/{slug}", tags=[slug])
    label = ASSET_LABELS[slug]

    def _label(obj) -> str:
        # Gold & Silver holdings are named by their metal in toasts.
        return obj.metal.capitalize() if slug == "gold" else label

    result = create_model(f"{read.__name__}Result", __base__=(read, Outcome))
    # POST also takes `paid_from`; PUT never does (editing a holding leaves its funding alone).
    create_in = create_model(
        f"{create.__name__}In", __base__=create, paid_from=(PaidFromBody | None, None)
    )

    def _with_message(obj, message: str):
        data = read.model_validate(obj).model_dump()
        return result(**data, message=message, description=_holding_name(obj))

    def _values(db: Session, body) -> dict:
        """Body as column values; a linked AMFI scheme overwrites scheme_name (snapshot)."""
        data = body.model_dump(exclude={"paid_from"})
        if slug == "nps":
            nps.require_scheme(db, data["scheme_id"])
        if data.get("scheme_code") is not None:
            data["scheme_name"] = amfi.require_scheme(db, data["scheme_code"]).name[:200]
        if data.get("issuer_id") is not None:
            issuer = fd_issuers.require_issuer(db, data["issuer_id"])
            data["bank"] = (issuer.short_name or issuer.name)[:200]
        master_id = data.get("master_id")
        if master_id is not None and slug == "stock":
            stock = stock_master.require_stock_master(db, master_id)
            data["name"] = stock.name[:200]
            data["symbol"] = stock_master.pick_stock_symbol(stock, data["exchange"], data["symbol"])
        elif master_id is not None and slug == "bond":
            bond = bond_master.require_bond_master(db, master_id)
            data["name"] = bond.name[:200]
            data["isin"] = bond.isin
        return data

    @sub.get("", response_model=list[read])
    def list_items(db: Session = Depends(get_db), user: User = Depends(current_user)):
        return db.scalars(
            select(model).where(model.user_id == user.id).order_by(model.id)
        ).all()

    @sub.post("", response_model=result, status_code=201)
    def create_item(
        body: create_in,  # type: ignore[valid-type]
        background: BackgroundTasks,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
        confirm_duplicate: bool = False,
    ):
        values = _values(db, body)
        today = sip_service.today_ist()
        funding = None
        if body.paid_from is not None:
            try:
                funding = fundings.plan(db, user.id, slug, values, body.paid_from, today)
            except fundings.FundingError as error:
                db.rollback()
                raise RequestValidationError(
                    [
                        {
                            "type": "value_error",
                            "loc": ("body", *error.loc),
                            "msg": error.message,
                            "input": "" if error.value is None else str(error.value),
                        }
                    ]
                ) from None
        if not confirm_duplicate:
            matches = duplicates.find_duplicates(db, slug, model, user.id, values)
            if matches:
                db.rollback()  # releases the account lock; nothing was debited
                return JSONResponse(
                    status_code=409, content=duplicates.duplicate_body(slug, matches)
                )
        obj = model(**values, user_id=user.id)
        db.add(obj)
        taken_from = None
        if funding is not None:
            db.flush()
            fundings.apply(db, user.id, slug, obj.id, funding)
            taken_from = fundings.paid_from_text(funding.amount, funding.cash.name)
        db.commit()
        db.refresh(obj)
        if slug == "nps":
            background.add_task(nps.sync_scheme_safely, obj.scheme_id)
        out = _with_message(obj, f"{_label(obj)} added")
        if taken_from is not None:
            out.description = f"{out.description} · {taken_from}"
        return out

    @sub.get("/{item_id}", response_model=read)
    def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
        return _get_or_404(db, model, item_id, user.id)

    @sub.put("/{item_id}", response_model=result)
    def replace_item(
        item_id: int,
        body: create,  # type: ignore[valid-type]
        background: BackgroundTasks,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        # Lock the row, then check its exits: a sale or settlement committed meanwhile is seen.
        obj = db.scalars(
            select(model)
            .where(model.id == item_id, model.user_id == user.id)
            .with_for_update(of=model)
        ).first()
        if obj is None:
            raise HTTPException(status_code=404, detail="Not found")
        values = _values(db, body)
        kinds = set(
            db.scalars(
                select(HoldingExit.kind).where(
                    HoldingExit.user_id == user.id,
                    HoldingExit.asset_type == slug,
                    HoldingExit.holding_id == obj.id,
                )
            )
        )
        if getattr(obj, "closed_on", None) is not None or "maturity" in kinds:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={
                    "message": HOLDING_CLOSED_MESSAGE,
                    "description": HOLDING_CLOSED_DESCRIPTION,
                },
            )
        if "sale" in kinds:
            errors = [
                {
                    "type": "value_error",
                    "loc": ("body", field),
                    "msg": SOLD_IN_PART_ERROR,
                    "input": "" if values.get(field) is None else str(values[field]),
                }
                for field in SOLD_IN_PART_FIELDS.get(slug, ())
                if _changed(getattr(obj, field), values.get(field))
            ]
            if errors:
                db.rollback()
                raise RequestValidationError(errors)
        for key, value in values.items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        if slug == "nps":
            background.add_task(nps.sync_scheme_safely, obj.scheme_id)
        return _with_message(obj, "Changes saved")

    @sub.delete("/{item_id}", response_model=Outcome)
    def delete_item(
        item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
    ):
        # Lock the row, then re-check it is still live: a second delete waits here and then 404s,
        # so the funding is refunded once.
        obj = db.scalars(
            select(model)
            .where(model.id == item_id, model.user_id == user.id)
            .with_for_update(of=model)
        ).first()
        if obj is None or obj.deleted_at is not None:
            raise HTTPException(status_code=404, detail="Not found")
        name = _holding_name(obj)
        deleted_label = _label(obj)
        obj.deleted_at = func.now()
        fundings.refund(db, user.id, slug, obj.id)
        db.commit()
        return Outcome(message=f"{deleted_label} deleted", description=name)

    @sub.post("/{item_id}/restore", response_model=Outcome)
    def restore_item(
        item_id: int,
        background: BackgroundTasks,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        obj = db.scalars(
            select(model)
            .where(model.id == item_id, model.user_id == user.id, model.deleted_at.is_not(None))
            .with_for_update(of=model)
            .execution_options(include_deleted=True)
        ).first()
        # Locked, and still deleted: a second restore waits here and then 404s (no second debit).
        if obj is None or obj.deleted_at is None:
            raise HTTPException(status_code=404, detail="Not found")
        try:
            fundings.restore(db, user.id, slug, obj.id)
        except fundings.FundingConflict as error:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail={"message": error.message, "description": error.description},
            ) from None
        obj.deleted_at = None
        db.commit()
        if slug == "nps":
            background.add_task(nps.sync_scheme_safely, obj.scheme_id)
        return Outcome(message=f"{_label(obj)} restored", description=_holding_name(obj))

    return sub


for _slug, (_model, _create, _read) in REGISTRY.items():
    router.include_router(_build_router(_slug, _model, _create, _read))
