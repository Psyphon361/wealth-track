from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.mf_scheme import MFNavOnDate, MFSchemeRead
from app.services import amfi, nav_history

router = APIRouter(prefix="/master", tags=["master"])


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


@router.get("/mf/{scheme_code}/nav", response_model=MFNavOnDate)
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
