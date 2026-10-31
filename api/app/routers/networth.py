from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.mf_master import MFNavHistory
from app.models.mf_transaction import MFTransaction
from app.models.user import User
from app.routers.assets import REGISTRY
from app.routers.portfolio import build_dashboard, load_groups
from app.schemas.networth import NetWorthHistoryResponse
from app.services import networth, stock_history

router = APIRouter(tags=["networth"])


def _fetch_records(bind: Any, user_id: int) -> dict[str, list[Any]]:
    def fetch(model: Any) -> list[Any]:
        # Own session per table so the queries share one network round trip.
        with Session(bind, autoflush=False, expire_on_commit=False) as session:
            stmt = select(model).where(model.user_id == user_id).order_by(model.id)
            return list(session.scalars(stmt).all())

    with ThreadPoolExecutor(max_workers=len(REGISTRY)) as pool:
        futures = {slug: pool.submit(fetch, model) for slug, (model, _c, _r) in REGISTRY.items()}
        return {slug: f.result() for slug, f in futures.items()}


def _fetch_navs(
    bind: Any, codes: set[int], start: date, end: date
) -> dict[int, list[tuple[date, Any]]]:
    out: dict[int, list[tuple[date, Any]]] = {}
    if not codes:
        return out
    stmt = (
        select(MFNavHistory.scheme_code, MFNavHistory.nav_date, MFNavHistory.nav)
        .where(
            MFNavHistory.scheme_code.in_(codes),
            MFNavHistory.nav_date >= start,
            MFNavHistory.nav_date <= end,
        )
        .order_by(MFNavHistory.scheme_code, MFNavHistory.nav_date)
    )
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for code, nav_date, nav in session.execute(stmt).all():
            out.setdefault(code, []).append((nav_date, nav))
    return out


def _fetch_closes(bind: Any, ids: set[int], end: date) -> dict[int, list[tuple[date, Any]]]:
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        return stock_history.closes_between(session, ids, date(1900, 1, 1), end)


def _fetch_txns(bind: Any, mf_ids: list[int]) -> dict[int, list[MFTransaction]]:
    out: dict[int, list[MFTransaction]] = {}
    if not mf_ids:
        return out
    stmt = select(MFTransaction).where(MFTransaction.mutual_fund_id.in_(mf_ids))
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        for t in session.scalars(stmt).all():
            out.setdefault(t.mutual_fund_id, []).append(t)
    return out


def load_history(
    db: Session, user_id: int, range_key: str, today: date | None = None
) -> dict[str, Any]:
    today = today or date.today()
    bind = db.get_bind()
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups_future = pool.submit(load_groups, db, user_id, today)
        records = _fetch_records(bind, user_id)
        mfs = records["mf"]
        stocks = records["stock"]
        txn_future = pool.submit(_fetch_txns, bind, [m.id for m in mfs])
        codes = {m.scheme_code for m in mfs if m.scheme_code is not None}
        txns = txn_future.result()
        start = networth.earliest_start(records, txns)
        if start is None:
            return {"range": range_key, "points": [], "stocks_at_cost_before": None}
        first = networth.range_start(range_key, today) or start
        # A little before the first day so every day has a NAV on or before it.
        nav_future = pool.submit(_fetch_navs, bind, codes, first - timedelta(days=14), today)
        closes_future = pool.submit(
            _fetch_closes, bind, {s.master_id for s in stocks if s.master_id is not None}, today
        )
        groups = groups_future.result()
        navs = nav_future.result()
        closes = closes_future.result()
    totals = build_dashboard(groups)
    return networth.build_history(
        range_key,
        today,
        records,
        navs,
        closes,
        txns,
        (totals["total_invested"], totals["total_current"]),
    )


@router.get("/networth/history", response_model=NetWorthHistoryResponse)
def get_history(
    range: Literal["1m", "6m", "1y", "all"] = "1y",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    return load_history(db, user.id, range)
