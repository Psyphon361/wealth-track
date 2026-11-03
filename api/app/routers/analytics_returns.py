import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db, read_bind
from app.deps import current_user
from app.models.mf_transaction import MFTransaction
from app.models.mf_master import MFMaster, MFNavHistory, MFNavHistorySync, MFNavLatest
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
from app.services.analytics_benchmark import BENCHMARK_SCHEME_CODE, BenchmarkNavs
from app.services.nav_history import NavSourceError, resolve_nav

logger = logging.getLogger(__name__)

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
    """NAV on or just before the start date, per NPS holding id; absent when history lacks it.
    One query for all active NPS holdings."""
    wanted = [
        (item["id"], item["scheme_id"], date.fromisoformat(str(item["start_date"])[:10]))
        for group in groups
        if group["type"] == "nps"
        for item in group["items"]
        if item.get("status") == "active"
    ]
    if not wanted:
        return {}
    window = timedelta(days=NPS_START_NAV_WINDOW_DAYS)
    stmt = select(NpsNavHistory.scheme_id, NpsNavHistory.nav_date, NpsNavHistory.nav).where(
        NpsNavHistory.scheme_id.in_({w[1] for w in wanted}),
        NpsNavHistory.nav_date >= min(w[2] for w in wanted) - window,
        NpsNavHistory.nav_date <= max(w[2] for w in wanted),
    )
    by_scheme: dict[Any, list[tuple[date, Decimal]]] = {}
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for row in session.execute(stmt):
            by_scheme.setdefault(row.scheme_id, []).append((row.nav_date, row.nav))
    out: dict[int, Decimal] = {}
    for hid, scheme_id, start in wanted:
        in_window = [
            r for r in by_scheme.get(scheme_id, []) if start - window <= r[0] <= start
        ]
        if in_window:
            out[hid] = max(in_window, key=lambda r: r[0])[1]
    return out


def _refresh_benchmark_history(bind: Any, read: Any) -> None:
    """Fetch the index fund's history from mfapi.in only on first ever use (no sync row). A stale
    history is served as stored; the daily AMFI import keeps it current (SPEC §9)."""
    code = BENCHMARK_SCHEME_CODE
    with Session(read, autoflush=False, expire_on_commit=False) as session:
        sync = session.get(MFNavHistorySync, code)
    if sync is not None:
        return
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        try:
            # date.min is never served from cache, so this fetches.
            resolve_nav(session, code, date.min)
        except NavSourceError:
            logger.warning("Benchmark NAV fetch failed for scheme %s", code, exc_info=True)
            session.rollback()


def _fetch_benchmark_navs(bind: Any, read: Any, since: date | None = None) -> BenchmarkNavs | None:
    """The index fund's NAVs from the NAV on or before `since` (all of them when None) to the
    latest. `bind` writes the on-demand history store; `read` is the autocommit bind for reads.
    None when no NAV is available."""
    code = BENCHMARK_SCHEME_CODE
    _refresh_benchmark_history(bind, read)

    def on_own_session(fn: Any) -> Any:
        with Session(read, autoflush=False, expire_on_commit=False) as session:
            return fn(session)

    def history(session: Session) -> list[Any]:
        stmt = select(MFNavHistory.nav_date, MFNavHistory.nav).where(
            MFNavHistory.scheme_code == code
        )
        if since is not None:
            stmt = stmt.where(MFNavHistory.nav_date >= since)
        return list(session.execute(stmt))

    def before_since(session: Session) -> list[Any]:
        if since is None:
            return []
        stmt = (
            select(MFNavHistory.nav_date, MFNavHistory.nav)
            .where(MFNavHistory.scheme_code == code, MFNavHistory.nav_date < since)
            .order_by(MFNavHistory.nav_date.desc())
            .limit(1)
        )
        return list(session.execute(stmt))

    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = [
            pool.submit(on_own_session, fn)
            for fn in (
                history,
                before_since,
                lambda s: s.get(MFNavLatest, code),
                lambda s: s.get(MFMaster, code),
            )
        ]
        found, anchor, latest, master = (p.result() for p in parts)
    rows = {r.nav_date: r.nav for r in [*found, *anchor]}
    if latest is not None:
        rows[latest.nav_date] = latest.nav
    if not rows:
        return None
    return BenchmarkNavs(
        scheme_name=master.name if master else "UTI Nifty 50 Index Fund",
        rows=sorted(rows.items()),
    )


@router.get("/analytics/returns", response_model=AnalyticsReturns)
def get_returns(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """XIRR overall, per class and per type, best/worst holdings, exclusions and reference rates."""
    today = date.today()
    write_bind = db.get_bind()
    bind = read_bind(db)
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
        benchmark_loader=lambda since: _fetch_benchmark_navs(write_bind, bind, since),
    )
