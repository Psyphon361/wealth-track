from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import create_model
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.db import Base, get_db
from app.deps import current_user
from app.models import Bond, Cash, FixedDeposit, Gold, MutualFund, Nps, Other, Pf, RecurringDeposit, Stock, User
from app.schemas.messages import Outcome
from app.services import amfi, bond_master, fd_issuers, nps, stock_master

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

    def _with_message(obj, message: str):
        data = read.model_validate(obj).model_dump()
        return result(**data, message=message, description=_holding_name(obj))

    def _values(db: Session, body) -> dict:
        """Body as column values; a linked AMFI scheme overwrites scheme_name (snapshot)."""
        data = body.model_dump()
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
        body: create,  # type: ignore[valid-type]
        background: BackgroundTasks,
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        obj = model(**_values(db, body), user_id=user.id)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        if slug == "nps":
            background.add_task(nps.sync_scheme_safely, obj.scheme_id)
        return _with_message(obj, f"{_label(obj)} added")

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
        obj = _get_or_404(db, model, item_id, user.id)
        for key, value in _values(db, body).items():
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
        obj = _get_or_404(db, model, item_id, user.id)
        name = _holding_name(obj)
        deleted_label = _label(obj)
        obj.deleted_at = func.now()
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
            .execution_options(include_deleted=True)
        ).first()
        if obj is None:
            raise HTTPException(status_code=404, detail="Not found")
        obj.deleted_at = None
        db.commit()
        if slug == "nps":
            background.add_task(nps.sync_scheme_safely, obj.scheme_id)
        return Outcome(message=f"{_label(obj)} restored", description=_holding_name(obj))

    return sub


for _slug, (_model, _create, _read) in REGISTRY.items():
    router.include_router(_build_router(_slug, _model, _create, _read))
