from fastapi import APIRouter, Depends, HTTPException
from pydantic import create_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.db import Base, get_db
from app.models import Bond, FixedDeposit, MutualFund, RecurringDeposit, Stock
from app.schemas.messages import Outcome
from app.services import amfi, securities

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


def _get_or_404(db: Session, model: type[Base], item_id: int):
    obj = db.get(model, item_id)
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
        security_id = data.get("security_id")
        if security_id is not None and slug == "stock":
            security = securities.require_security(
                db, security_id, ("stock", "etf"), securities.UNKNOWN_STOCK_MESSAGE
            )
            data["name"] = security.name[:200]
            data["symbol"] = securities.pick_stock_symbol(security, data["exchange"], data["symbol"])
        elif security_id is not None and slug == "bond":
            security = securities.require_security(
                db, security_id, ("bond",), securities.UNKNOWN_BOND_MESSAGE
            )
            data["name"] = security.name[:200]
            data["isin"] = security.isin
        return data

    @sub.get("", response_model=list[read])
    def list_items(db: Session = Depends(get_db)):
        return db.scalars(select(model).order_by(model.id)).all()

    @sub.post("", response_model=result, status_code=201)
    def create_item(body: create, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = model(**_values(db, body))
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return _with_message(obj, f"{label} added")

    @sub.get("/{item_id}", response_model=read)
    def get_item(item_id: int, db: Session = Depends(get_db)):
        return _get_or_404(db, model, item_id)

    @sub.put("/{item_id}", response_model=result)
    def replace_item(item_id: int, body: create, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = _get_or_404(db, model, item_id)
        for key, value in _values(db, body).items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        return _with_message(obj, "Changes saved")

    @sub.delete("/{item_id}", response_model=Outcome)
    def delete_item(item_id: int, db: Session = Depends(get_db)):
        obj = _get_or_404(db, model, item_id)
        name = _holding_name(obj)
        db.delete(obj)
        db.commit()
        return Outcome(message=f"{label} deleted", description=name)

    return sub


for _slug, (_model, _create, _read) in REGISTRY.items():
    router.include_router(_build_router(_slug, _model, _create, _read))
