from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.mf_transaction import MFTransaction
from app.models.mutual_fund import MutualFund
from app.models.nps_master import NpsNavHistory
from app.models.user import User
from app.routers.analytics import (
    _fetch_bond_masters,
    _fetch_mf_masters,
    _fetch_stock_masters,
)
from app.routers.portfolio import load_groups
from app.schemas.analytics_returns import AnalyticsReturns
from app.services import analytics_returns

router = APIRouter(tags=["analytics"])

# A start NAV counts only when the history has a NAV this close on or before the start date.
NPS_START_NAV_WINDOW_DAYS = 7


def _fetch_mf_transactions(bind: Any, user_id: int) -> dict[int, list[Any]]:
    """The user's MF purchases and redemptions with amounts, oldest first, by mutual_funds.id.
    (The analytics helper of the same name leaves out the amount.)"""
    stmt = (
        select(
            MFTransaction.mutual_fund_id,
            MFTransaction.txn_date,
            MFTransaction.kind,
            MFTransaction.units,
            MFTransaction.amount,
        )
        .join(MutualFund, MutualFund.id == MFTransaction.mutual_fund_id)
        .where(MutualFund.user_id == user_id)
        .order_by(MFTransaction.txn_date, MFTransaction.id)
    )
    out: dict[int, list[Any]] = {}
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for row in session.execute(stmt):
            out.setdefault(row.mutual_fund_id, []).append(row)
    return out


def _fetch_nps_start_navs(bind: Any, groups: list[dict[str, Any]]) -> dict[int, Decimal]:
    """NAV on or just before the start date, per NPS holding id; absent when history lacks it."""
    out: dict[int, Decimal] = {}
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for group in groups:
            if group["type"] != "nps":
                continue
            for item in group["items"]:
                if item.get("status") != "active":
                    continue
                start = date.fromisoformat(str(item["start_date"])[:10])
                row = session.execute(
                    select(NpsNavHistory.nav)
                    .where(
                        NpsNavHistory.scheme_id == item["scheme_id"],
                        NpsNavHistory.nav_date <= start,
                        NpsNavHistory.nav_date >= start - timedelta(days=NPS_START_NAV_WINDOW_DAYS),
                    )
                    .order_by(NpsNavHistory.nav_date.desc())
                    .limit(1)
                ).first()
                if row is not None:
                    out[item["id"]] = row.nav
    return out


@router.get("/analytics/returns", response_model=AnalyticsReturns)
def get_returns(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """XIRR overall, per class and per type, best/worst holdings, exclusions and reference rates."""
    today = date.today()
    bind = db.get_bind()
    with ThreadPoolExecutor(max_workers=4) as pool:
        stocks = pool.submit(_fetch_stock_masters, bind, user.id)
        bonds = pool.submit(_fetch_bond_masters, bind, user.id)
        funds = pool.submit(_fetch_mf_masters, bind, user.id)
        txns = pool.submit(_fetch_mf_transactions, bind, user.id)
        groups = load_groups(db, user.id, today)
        stock_masters, bond_masters = stocks.result(), bonds.result()
        mf_masters, mf_transactions = funds.result(), txns.result()
    return analytics_returns.returns(
        groups,
        today,
        stock_masters=stock_masters,
        bond_masters=bond_masters,
        mf_masters=mf_masters,
        mf_transactions=mf_transactions,
        nps_start_navs=_fetch_nps_start_navs(bind, groups),
    )
