from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models.user import User
from app.routers.analytics import _fetch_issuer_masters
from app.routers.portfolio import load_groups
from app.schemas.analytics_tax import AnalyticsTax
from app.services import analytics_tax

router = APIRouter(tags=["analytics"])


@router.get("/analytics/tax", response_model=AnalyticsTax)
def get_tax(
    fy: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Interest and TDS to expect per bank or company for a financial year (SPEC §9)."""
    today = date.today()
    allowed = [f["start_year"] for f in analytics_tax.available_fys(today)]
    if fy is not None and fy not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid financial year",
                "description": (
                    f"Choose {analytics_tax.fy_label(allowed[0])} (this year) "
                    f"or {analytics_tax.fy_label(allowed[1])} (last year)."
                ),
            },
        )
    groups = load_groups(db, user.id, today)
    has_deposits = any(g["items"] for g in groups if g["type"] in ("fd", "rd"))
    issuer_masters = _fetch_issuer_masters(read_bind(db)) if has_deposits else {}
    return analytics_tax.tax_overview(groups, issuer_masters, today, fy)
