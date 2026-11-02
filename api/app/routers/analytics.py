from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.bond import Bond
from app.models.bond_master import BondMaster
from app.models.fd_issuer_master import FdIssuerMaster
from app.models.mf_master import MFMaster
from app.models.mf_transaction import MFTransaction
from app.models.mutual_fund import MutualFund
from app.models.stock import Stock
from app.models.stock_master import StockMaster
from app.models.user import User
from app.routers.portfolio import load_groups
from app.schemas.analytics import AnalyticsOverview
from app.services import analytics

router = APIRouter(tags=["analytics"])


def _rows(bind: Any, stmt: Any, key: str) -> dict[Any, Any]:
    """Rows of `stmt` keyed by column `key`, on this part's own session."""
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        return {getattr(row, key): row for row in session.execute(stmt)}


def _fetch_stock_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(Stock.master_id).where(Stock.user_id == user_id, Stock.master_id.is_not(None))
    stmt = select(StockMaster.id, StockMaster.kind, StockMaster.name).where(
        StockMaster.id.in_(held)
    )
    return _rows(bind, stmt, "id")


def _fetch_bond_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(Bond.master_id).where(Bond.user_id == user_id, Bond.master_id.is_not(None))
    stmt = select(BondMaster.id, BondMaster.bond_type, BondMaster.issuer).where(
        BondMaster.id.in_(held)
    )
    return _rows(bind, stmt, "id")


def _fetch_mf_masters(bind: Any, user_id: int) -> dict[int, Any]:
    held = select(MutualFund.scheme_code).where(
        MutualFund.user_id == user_id, MutualFund.scheme_code.is_not(None)
    )
    stmt = select(
        MFMaster.scheme_code, MFMaster.amc, MFMaster.amfi_category, MFMaster.name
    ).where(MFMaster.scheme_code.in_(held))
    return _rows(bind, stmt, "scheme_code")


def _fetch_mf_transactions(bind: Any, user_id: int) -> dict[int, list[Any]]:
    """Purchases and redemptions of the user's funds, grouped by mutual_funds.id."""
    stmt = (
        select(
            MFTransaction.mutual_fund_id,
            MFTransaction.txn_date,
            MFTransaction.kind,
            MFTransaction.units,
        )
        .join(MutualFund, MutualFund.id == MFTransaction.mutual_fund_id)
        .where(MutualFund.user_id == user_id)
    )
    out: dict[int, list[Any]] = {}
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for row in session.execute(stmt):
            out.setdefault(row.mutual_fund_id, []).append(row)
    return out


def _fetch_issuer_masters(bind: Any) -> dict[int, Any]:
    """Every issuer: a bank is also matched by its entered name, and merges point at any row."""
    stmt = select(
        FdIssuerMaster.id,
        FdIssuerMaster.name,
        FdIssuerMaster.short_name,
        FdIssuerMaster.category,
        FdIssuerMaster.dicgc_insured,
        FdIssuerMaster.merged_into_id,
    )
    return _rows(bind, stmt, "id")


@router.get("/analytics/overview", response_model=AnalyticsOverview)
def get_overview(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Allocation, concentration, liquidity, maturities, bank safety and data health of the user."""
    today = date.today()
    bind = db.get_bind()
    # Master rows load concurrently with the valued holdings, each on its own session.
    with ThreadPoolExecutor(max_workers=4) as pool:
        stocks = pool.submit(_fetch_stock_masters, bind, user.id)
        bonds = pool.submit(_fetch_bond_masters, bind, user.id)
        funds = pool.submit(_fetch_mf_masters, bind, user.id)
        txns = pool.submit(_fetch_mf_transactions, bind, user.id)
        groups = load_groups(db, user.id, today)
        stock_masters, bond_masters = stocks.result(), bonds.result()
        mf_masters, mf_transactions = funds.result(), txns.result()
    has_deposits = any(g["items"] for g in groups if g["type"] in ("fd", "rd"))
    issuer_masters = _fetch_issuer_masters(bind) if has_deposits else {}
    masters = {
        "stock_masters": stock_masters,
        "bond_masters": bond_masters,
        "mf_masters": mf_masters,
    }
    return {
        "as_of": today,
        "allocation": analytics.allocation(groups, **masters),
        "concentration": analytics.concentration(
            groups, **masters, issuer_masters=issuer_masters
        ),
        "liquidity": analytics.liquidity(
            groups, today=today, mf_masters=mf_masters, mf_transactions=mf_transactions
        ),
        "coming_up": analytics.coming_up(groups, today, bond_masters=bond_masters),
        "bank_safety": analytics.bank_safety(groups, issuer_masters),
        "data_health": analytics.data_health(groups, today),
    }
