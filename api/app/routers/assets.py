from fastapi import APIRouter, Depends, HTTPException
from pydantic import create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.db import Base, get_db
from app.deps import current_user
from app.models import Bond, FixedDeposit, MutualFund, RecurringDeposit, Stock, User
from app.schemas.messages import Outcome
from app.services import amfi, bond_master, stock_master

router = APIRouter(prefix="/assets")

# type slug -> (model, create schema, read schema)
REGISTRY = {
    "fd": (FixedDeposit, schemas.FixedDepositCreate, schemas.FixedDepositRead),
    "rd": (RecurringDeposit, schemas.RecurringDepositCreate, schemas.RecurringDepositRead),
    "stock": (Stock, schemas.StockCreate, schemas.StockRead),
    "bond": (Bond, schemas.BondCreate, schemas.BondRead),
    "mf": (MutualFund, schemas.MutualFundCreate, schemas.MutualFundRead),
}


ASSET_LABELS = {
    "fd": "Fixed deposit",
    "rd": "Recurring deposit",
    "stock": "Stock",
    "bond": "Bond",
    "mf": "Mutual fund",
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
    result = create_model(f"{read.__name__}Result", __base__=(read, Outcome))

    def _with_message(obj, message: str):
        data = read.model_validate(obj).model_dump()
        return result(**data, message=message, description=_holding_name(obj))

    def _values(db: Session, body) -> dict:
        """Body as column values; a linked AMFI scheme overwrites scheme_name (snapshot)."""
        data = body.model_dump()
        if data.get("scheme_code") is not None:
            data["scheme_name"] = amfi.require_scheme(db, data["scheme_code"]).name[:200]
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
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        obj = model(**_values(db, body), user_id=user.id)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return _with_message(obj, f"{label} added")

    @sub.get("/{item_id}", response_model=read)
    def get_item(item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
        return _get_or_404(db, model, item_id, user.id)

    @sub.put("/{item_id}", response_model=result)
    def replace_item(
        item_id: int,
        body: create,  # type: ignore[valid-type]
        db: Session = Depends(get_db),
        user: User = Depends(current_user),
    ):
        obj = _get_or_404(db, model, item_id, user.id)
        for key, value in _values(db, body).items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        return _with_message(obj, "Changes saved")

    @sub.delete("/{item_id}", response_model=Outcome)
    def delete_item(
        item_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)
    ):
        obj = _get_or_404(db, model, item_id, user.id)
        name = _holding_name(obj)
        db.delete(obj)
        db.commit()
        return Outcome(message=f"{label} deleted", description=name)

    return sub


for _slug, (_model, _create, _read) in REGISTRY.items():
    router.include_router(_build_router(_slug, _model, _create, _read))
