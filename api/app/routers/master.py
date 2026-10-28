from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.schemas.market_master import BondMasterRead, FdIssuerRead, StockMasterRead
from app.schemas.mf_scheme import MFNavOnDate, MFSchemeRead
from app.services import amfi, bond_master, fd_issuers, nav_history, stock_master

router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(current_user)])


@router.get("/mf", response_model=list[MFSchemeRead])
def search_mf(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return amfi.search_schemes(db, q, limit)


@router.get("/mf/{scheme_code}", response_model=MFSchemeRead)
def get_mf(scheme_code: int, db: Session = Depends(get_db)):
    scheme = amfi.get_scheme_with_nav(db, scheme_code)
    if scheme is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    return scheme


@router.get("/stock", response_model=list[StockMasterRead])
def search_stock(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return stock_master.search_stocks(db, q, limit)


@router.get("/stock/{master_id}", response_model=StockMasterRead)
def get_stock(master_id: int, db: Session = Depends(get_db)):
    stock = stock_master.get_stock_master(db, master_id)
    if stock is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Stock not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return stock


@router.get("/bond", response_model=list[BondMasterRead])
def search_bond(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return bond_master.search_bonds(db, q, limit)


@router.get("/bond/{master_id}", response_model=BondMasterRead)
def get_bond(master_id: int, db: Session = Depends(get_db)):
    bond = bond_master.get_bond_master(db, master_id)
    if bond is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Bond not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return bond


@router.get("/fd-issuer", response_model=list[FdIssuerRead])
def search_fd_issuer(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return fd_issuers.search_issuers(db, q, limit)


@router.get("/fd-issuer/{issuer_id}", response_model=FdIssuerRead)
def get_fd_issuer(issuer_id: int, db: Session = Depends(get_db)):
    issuer = fd_issuers.get_issuer(db, issuer_id)
    if issuer is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Issuer not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return issuer


@router.get("/mf/{scheme_code}/nav",response_model=MFNavOnDate)
def get_mf_nav(
    scheme_code: int,
    on_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    nav_history.validate_not_future(on_date)
    if amfi.get_scheme(db, scheme_code) is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    try:
        found = nav_history.resolve_nav(db, scheme_code, on_date)
    except nav_history.NavSourceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Couldn't fetch NAV history",
                "description": "The NAV source is unavailable. Try again shortly.",
            },
        ) from exc
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "NAV not available",
                "description": "No NAV published on or before this date.",
            },
        )
    return {"scheme_code": scheme_code, "requested_date": on_date, **found}
