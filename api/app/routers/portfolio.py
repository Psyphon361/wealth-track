from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models.user import User
from app.models.mf_master import MFNavLatest
from app.models.mutual_fund import MutualFund
from app.models.stock_price import StockPriceLatest
from app.routers.assets import REGISTRY
from app.schemas.summary import DashboardResponse, PortfolioResponse
from app.services import stock_prices, valuation

router = APIRouter(tags=["portfolio"])

LABELS = {
    "fd": "Fixed Deposits",
    "rd": "Recurring Deposits",
    "stock": "Stocks",
    "bond": "Bonds",
    "mf": "Mutual Funds",
}
_VALUERS = {
    "fd": valuation.value_fd,
    "rd": valuation.value_rd,
    "stock": valuation.value_stock,
    "bond": valuation.value_bond,
    "mf": valuation.value_mf,
}
_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _item(record: Any, read_schema: type, computed: dict[str, Any]) -> dict[str, Any]:
    item = read_schema.model_validate(record).model_dump(mode="json")
    for key, value in computed.items():
        if isinstance(value, Decimal):
            value = float(value)
        elif isinstance(value, date):
            value = value.isoformat()
        item[key] = value
    return item


def _fetch_navs(bind: Any, user_id: int) -> dict[int, tuple[Decimal, date]]:
    """Latest NAV for only the schemes this user holds, in a single query."""
    held = select(MutualFund.scheme_code).where(
        MutualFund.scheme_code.is_not(None), MutualFund.user_id == user_id
    )
    stmt = select(MFNavLatest).where(MFNavLatest.scheme_code.in_(held))
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        return {r.scheme_code: (r.nav, r.nav_date) for r in session.scalars(stmt).all()}


def _value(
    slug: str,
    record: Any,
    today: date,
    navs: dict[int, tuple[Decimal, date]],
    prices: dict[int, StockPriceLatest],
):
    if slug == "mf":
        nav, nav_date = navs.get(record.scheme_code, (None, None))
        return valuation.value_mf(record, today, nav=nav, nav_date=nav_date)
    if slug == "stock":
        row = prices.get(record.master_id) if record.master_id is not None else None
        out = valuation.value_stock(record, today, price=row.price if row else None)
        out["price"] = row.price if row else None
        out["prev_close"] = row.prev_close if row else None
        out["day_change_pct"] = (
            stock_prices.day_change_pct(row.price, row.prev_close) if row else None
        )
        out["price_time"] = row.price_time.isoformat() if row and row.price_time else None
        out["price_source"] = row.source if row else None
        return out
    return _VALUERS[slug](record, today)


def _fetch_stocks(
    bind: Any, user_id: int
) -> tuple[list[Any], dict[int, StockPriceLatest]]:
    """The user's stocks plus last close prices, on this part's own session."""
    model = REGISTRY["stock"][0]
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        records = list(
            session.scalars(
                select(model).where(model.user_id == user_id).order_by(model.id)
            ).all()
        )
        return records, _prices_for(session, records)


def _prices_for(session: Session, records: list[Any]) -> dict[int, StockPriceLatest]:
    ids = {r.master_id for r in records if r.master_id is not None}
    return stock_prices.latest_prices(session, ids)


def build_groups(
    records_by_type: dict[str, list[Any]],
    today: date,
    navs: dict[int, tuple[Decimal, date]] | None = None,
    prices: dict[int, StockPriceLatest] | None = None,
) -> list[dict[str, Any]]:
    """Value every holding; returns the 5 groups in fixed order."""
    navs = navs or {}
    prices = prices or {}
    groups = []
    for slug, (_model, _create, read_schema) in REGISTRY.items():
        computed = [_value(slug, r, today, navs, prices) for r in records_by_type.get(slug, [])]
        items = [
            _item(r, read_schema, c)
            for r, c in zip(records_by_type.get(slug, []), computed, strict=True)
        ]
        active = [c for c in computed if c["status"] == "active"]
        group = {
            "type": slug,
            "label": LABELS[slug],
            "items": items,
            "totals": valuation.aggregate(active),
            "count": len(active),
            "matured_count": len(computed) - len(active),
        }
        if slug == "stock":
            times = [
                prices[r.master_id].price_time
                for r in records_by_type.get(slug, [])
                if r.master_id in prices and prices[r.master_id].price_time
            ]
            group["prices_as_of"] = max(times) if times else None
        groups.append(group)
    return groups


def load_groups(db: Session, user_id: int, today: date | None = None) -> list[dict[str, Any]]:
    bind = db.get_bind()

    def fetch(model: Any) -> list[Any]:
        # Own session per table so the 5 queries share one network round trip.
        with Session(bind, autoflush=False, expire_on_commit=False) as session:
            stmt = select(model).where(model.user_id == user_id).order_by(model.id)
            return list(session.scalars(stmt).all())

    with ThreadPoolExecutor(max_workers=len(REGISTRY) + 1) as pool:
        futures = {
            slug: pool.submit(fetch, model)
            for slug, (model, _c, _r) in REGISTRY.items()
            if slug != "stock"
        }
        stock_future = pool.submit(_fetch_stocks, bind, user_id)
        nav_future = pool.submit(_fetch_navs, bind, user_id)
        records = {slug: future.result() for slug, future in futures.items()}
        records["stock"], prices = stock_future.result()
        navs = nav_future.result()
    return build_groups(records, today or date.today(), navs, prices)


def load_group(
    db: Session, slug: str, user_id: int, today: date | None = None
) -> dict[str, Any]:
    """Fetch and value a single asset type (MF adds one NAV query, run concurrently)."""
    model = REGISTRY[slug][0]
    stmt = select(model).where(model.user_id == user_id).order_by(model.id)
    if slug == "mf":
        with ThreadPoolExecutor(max_workers=1) as pool:
            nav_future = pool.submit(_fetch_navs, db.get_bind(), user_id)
            records = list(db.scalars(stmt).all())
            navs = nav_future.result()
    else:
        records = list(db.scalars(stmt).all())
        navs = {}
    prices = _prices_for(db, records) if slug == "stock" else {}
    groups = build_groups({slug: records}, today or date.today(), navs, prices)
    return next(g for g in groups if g["type"] == slug)


def load_holding(
    db: Session, slug: str, user_id: int, item_id: int, today: date | None = None
) -> tuple[Any, dict[str, Any]] | None:
    """One of the user's holdings as (record, grid item), or None if not theirs."""
    model = REGISTRY[slug][0]
    record = db.scalars(
        select(model).where(model.id == item_id, model.user_id == user_id)
    ).first()
    if record is None:
        return None
    navs: dict[int, tuple[Decimal, date]] = {}
    if slug == "mf" and record.scheme_code is not None:
        row = db.get(MFNavLatest, record.scheme_code)
        if row is not None:
            navs[row.scheme_code] = (row.nav, row.nav_date)
    prices = _prices_for(db, [record]) if slug == "stock" else {}
    groups = build_groups({slug: [record]}, today or date.today(), navs, prices)
    group = next(g for g in groups if g["type"] == slug)
    return record, group["items"][0]


def build_dashboard(groups: list[dict[str, Any]]) -> dict[str, Any]:
    total_invested = _q(sum((g["totals"]["invested"] for g in groups), Decimal("0")))
    total_current = _q(sum((g["totals"]["current_value"] for g in groups), Decimal("0")))
    total_gain = _q(sum((g["totals"]["gain"] for g in groups), Decimal("0")))
    gain_pct = _q(total_gain / total_invested * 100) if total_invested else Decimal("0.00")
    by_type = []
    for g in groups:
        current = g["totals"]["current_value"]
        by_type.append(
            {
                "type": g["type"],
                "label": g["label"],
                "count": g["count"],
                "matured_count": g["matured_count"],
                "invested": g["totals"]["invested"],
                "current": current,
                "allocation_pct": _q(current / total_current * 100)
                if total_current
                else Decimal("0.00"),
            }
        )
    return {
        "total_invested": total_invested,
        "total_current": total_current,
        "total_gain": total_gain,
        "gain_pct": gain_pct,
        "by_type": by_type,
    }


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {"groups": load_groups(db, user.id)}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return build_dashboard(load_groups(db, user.id))
