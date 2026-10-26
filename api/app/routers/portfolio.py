from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.mf_master import MFNavLatest
from app.models.mutual_fund import MutualFund
from app.routers.assets import REGISTRY
from app.schemas.summary import DashboardResponse, PortfolioResponse
from app.services import valuation

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


def _fetch_navs(bind: Any) -> dict[int, tuple[Decimal, date]]:
    """Latest NAV for only the schemes held, in a single query."""
    held = select(MutualFund.scheme_code).where(MutualFund.scheme_code.is_not(None))
    stmt = select(MFNavLatest).where(MFNavLatest.scheme_code.in_(held))
    with Session(bind, autoflush=False, expire_on_commit=False) as session:
        return {r.scheme_code: (r.nav, r.nav_date) for r in session.scalars(stmt).all()}


def _value(slug: str, record: Any, today: date, navs: dict[int, tuple[Decimal, date]]):
    if slug == "mf":
        nav, nav_date = navs.get(record.scheme_code, (None, None))
        return valuation.value_mf(record, today, nav=nav, nav_date=nav_date)
    return _VALUERS[slug](record, today)


def build_groups(
    records_by_type: dict[str, list[Any]],
    today: date,
    navs: dict[int, tuple[Decimal, date]] | None = None,
) -> list[dict[str, Any]]:
    """Value every holding; returns the 5 groups in fixed order."""
    navs = navs or {}
    groups = []
    for slug, (_model, _create, read_schema) in REGISTRY.items():
        computed = [_value(slug, r, today, navs) for r in records_by_type.get(slug, [])]
        items = [
            _item(r, read_schema, c)
            for r, c in zip(records_by_type.get(slug, []), computed, strict=True)
        ]
        active = [c for c in computed if c["status"] == "active"]
        groups.append(
            {
                "type": slug,
                "label": LABELS[slug],
                "items": items,
                "totals": valuation.aggregate(active),
                "count": len(active),
                "matured_count": len(computed) - len(active),
            }
        )
    return groups


def load_groups(db: Session, today: date | None = None) -> list[dict[str, Any]]:
    bind = db.get_bind()

    def fetch(model: Any) -> list[Any]:
        # Own session per table so the 5 queries share one network round trip.
        with Session(bind, autoflush=False, expire_on_commit=False) as session:
            return list(session.scalars(select(model).order_by(model.id)).all())

    with ThreadPoolExecutor(max_workers=len(REGISTRY) + 1) as pool:
        futures = {
            slug: pool.submit(fetch, model) for slug, (model, _c, _r) in REGISTRY.items()
        }
        nav_future = pool.submit(_fetch_navs, bind)
        records = {slug: future.result() for slug, future in futures.items()}
        navs = nav_future.result()
    return build_groups(records, today or date.today(), navs)


def load_group(db: Session, slug: str, today: date | None = None) -> dict[str, Any]:
    """Fetch and value a single asset type (MF adds one NAV query, run concurrently)."""
    model = REGISTRY[slug][0]
    if slug == "mf":
        with ThreadPoolExecutor(max_workers=1) as pool:
            nav_future = pool.submit(_fetch_navs, db.get_bind())
            records = list(db.scalars(select(model).order_by(model.id)).all())
            navs = nav_future.result()
    else:
        records = list(db.scalars(select(model).order_by(model.id)).all())
        navs = {}
    groups = build_groups({slug: records}, today or date.today(), navs)
    return next(g for g in groups if g["type"] == slug)


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
def get_portfolio(db: Session = Depends(get_db)):
    return {"groups": load_groups(db)}


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)):
    return build_dashboard(load_groups(db))
