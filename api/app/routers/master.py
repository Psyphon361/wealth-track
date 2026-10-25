from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.mf_scheme import MFSchemeRead
from app.services import amfi

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
