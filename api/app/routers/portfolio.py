from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
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


def build_groups(records_by_type: dict[str, list[Any]], today: date) -> list[dict[str, Any]]:
    """Value every holding; returns the 5 groups in fixed order."""
    groups = []
    for slug, (_model, _create, read_schema) in REGISTRY.items():
        computed = [_VALUERS[slug](r, today) for r in records_by_type.get(slug, [])]
        items = [
            _item(r, read_schema, c)
            for r, c in zip(records_by_type.get(slug, []), computed, strict=True)
        ]
        groups.append(
            {
                "type": slug,
                "label": LABELS[slug],
                "items": items,
                "totals": valuation.aggregate(computed),
                "count": len(items),
            }
        )
    return groups


def load_groups(db: Session, today: date | None = None) -> list[dict[str, Any]]:
    bind = db.get_bind()

    def fetch(model: Any) -> list[Any]:
        # Own session per table so the 5 queries share one network round trip.
        with Session(bind, autoflush=False, expire_on_commit=False) as session:
            return list(session.scalars(select(model).order_by(model.id)).all())

    with ThreadPoolExecutor(max_workers=len(REGISTRY)) as pool:
        futures = {
            slug: pool.submit(fetch, model) for slug, (model, _c, _r) in REGISTRY.items()
        }
        records = {slug: future.result() for slug, future in futures.items()}
    return build_groups(records, today or date.today())


def build_dashboard(groups: list[dict[str, Any]]) -> dict[str, Any]:
    total_invested = _q(sum((g["totals"]["invested"] for g in groups), Decimal("0")))
    total_current = _q(sum((g["totals"]["current_value"] for g in groups), Decimal("0")))
    total_gain = total_current - total_invested
    gain_pct = _q(total_gain / total_invested * 100) if total_invested else Decimal("0.00")
    by_type = []
    for g in groups:
        current = g["totals"]["current_value"]
        by_type.append(
            {
                "type": g["type"],
                "label": g["label"],
                "count": g["count"],
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
