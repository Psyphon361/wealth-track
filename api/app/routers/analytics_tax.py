from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models.bond import Bond
from app.models.bond_master import BondMaster
from app.models.user import User
from app.routers.analytics import _fetch_issuer_masters, _rows
from app.routers.portfolio import load_groups
from app.schemas.analytics_cashflows import AnalyticsInflows
from app.schemas.analytics_tax import AnalyticsTax, BondScheduleResponse
from app.services import analytics_tax, bond_schedule, cashflows

router = APIRouter(tags=["analytics"])


def _fetch_bond_masters(bind: Any, user_id: int) -> dict[int, Any]:
    """The bond_master rows of the user's held bonds, with the coupon fields the tax tab needs."""
    held = select(Bond.master_id).where(Bond.user_id == user_id, Bond.master_id.is_not(None))
    stmt = select(
        BondMaster.id,
        BondMaster.bond_type,
        BondMaster.issuer,
        BondMaster.face_value,
        BondMaster.coupon_rate,
        BondMaster.coupon_type,
        BondMaster.interest_frequency,
        BondMaster.issue_date,
        BondMaster.issue_price,
    ).where(BondMaster.id.in_(held))
    return _rows(bind, stmt, "id")


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
    bind = read_bind(db)
    issuer_masters = _fetch_issuer_masters(bind) if has_deposits else {}
    has_bonds = any(g["items"] for g in groups if g["type"] == "bond")
    bond_masters = _fetch_bond_masters(bind, user.id) if has_bonds else {}
    return analytics_tax.tax_overview(groups, issuer_masters, today, fy, bond_masters)


@router.get("/analytics/bond-schedule", response_model=BondScheduleResponse)
def get_bond_schedule(
    id: Annotated[int | None, Query()] = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Estimated coupon and redemption schedule of the user's bonds, or of one bond (SPEC §9)."""
    today = date.today()
    groups = load_groups(db, user.id, today)
    items = [i for g in groups if g["type"] == "bond" for i in g["items"]]
    if id is not None:
        items = [i for i in items if i["id"] == id]
        if not items:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": "Bond not found",
                    "description": "This bond doesn't exist or was deleted.",
                },
            )
    bond_masters = _fetch_bond_masters(read_bind(db), user.id) if items else {}
    views = [
        bond_schedule.schedule_view(i, bond_masters.get(i.get("master_id")), today) for i in items
    ]
    bonds = [v for v in views if v is not None]
    return {"as_of": today, "bonds": bonds, "excluded": len(views) - len(bonds)}


@router.get("/analytics/inflows", response_model=AnalyticsInflows)
def get_inflows(
    months: Annotated[int, Query()] = 12,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    """Money coming in by month from bond coupons, FD payouts and maturities (SPEC §9)."""
    if months not in (12, 24):
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Invalid period",
                "description": "Choose 12 or 24 months.",
            },
        )
    today = date.today()
    groups = load_groups(db, user.id, today)
    has_bonds = any(g["items"] for g in groups if g["type"] == "bond")
    bond_masters = _fetch_bond_masters(read_bind(db), user.id) if has_bonds else {}
    return cashflows.inflows(groups, bond_masters, today, months)
