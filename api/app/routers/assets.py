from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.db import Base, get_db
from app.models import Bond, FixedDeposit, MutualFund, RecurringDeposit, Stock

router = APIRouter(prefix="/assets")

# type slug -> (model, create schema, read schema)
REGISTRY = {
    "fd": (FixedDeposit, schemas.FixedDepositCreate, schemas.FixedDepositRead),
    "rd": (RecurringDeposit, schemas.RecurringDepositCreate, schemas.RecurringDepositRead),
    "stock": (Stock, schemas.StockCreate, schemas.StockRead),
    "bond": (Bond, schemas.BondCreate, schemas.BondRead),
    "mf": (MutualFund, schemas.MutualFundCreate, schemas.MutualFundRead),
}


def _get_or_404(db: Session, model: type[Base], item_id: int):
    obj = db.get(model, item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Not found")
    return obj


def _build_router(slug: str, model, create, read) -> APIRouter:
    sub = APIRouter(prefix=f"/{slug}", tags=[slug])

    @sub.get("", response_model=list[read])
    def list_items(db: Session = Depends(get_db)):
        return db.scalars(select(model).order_by(model.id)).all()

    @sub.post("", response_model=read, status_code=201)
    def create_item(body: create, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = model(**body.model_dump())
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    @sub.get("/{item_id}", response_model=read)
    def get_item(item_id: int, db: Session = Depends(get_db)):
        return _get_or_404(db, model, item_id)

    @sub.put("/{item_id}", response_model=read)
    def replace_item(item_id: int, body: create, db: Session = Depends(get_db)):  # type: ignore[valid-type]
        obj = _get_or_404(db, model, item_id)
        for key, value in body.model_dump().items():
            setattr(obj, key, value)
        db.commit()
        db.refresh(obj)
        return obj

    @sub.delete("/{item_id}", status_code=204)
    def delete_item(item_id: int, db: Session = Depends(get_db)) -> Response:
        db.delete(_get_or_404(db, model, item_id))
        db.commit()
        return Response(status_code=204)

    return sub


for _slug, (_model, _create, _read) in REGISTRY.items():
    router.include_router(_build_router(_slug, _model, _create, _read))
