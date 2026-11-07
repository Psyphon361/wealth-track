from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Other, User
from app.schemas.assets import (
    GOLD_METAL_PURITIES,
    GOLD_PURITY_ERROR,
    SILVER_PURITIES,
    GoldMetal,
    GoldPurity,
)
from app.schemas.exits import StockClose
from app.schemas.gold import GoldRateOnDate
from app.schemas.market_master import BondMasterRead, FdIssuerRead, NpsMasterRead, StockMasterRead
from app.schemas.mf_scheme import MFNavOnDate, MFSchemeRead
from app.services import (
    amfi,
    bond_master,
    fd_issuers,
    gold_rates,
    nav_history,
    nps,
    stock_history,
    stock_master,
    stock_prices,
)

router = APIRouter(prefix="/master", tags=["master"], dependencies=[Depends(current_user)])


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


@router.get("/nps", response_model=list[NpsMasterRead])
def search_nps(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return nps.search_schemes(db, q, limit)


@router.get("/nps/{scheme_id}", response_model=NpsMasterRead)
def get_nps(scheme_id: str, db: Session = Depends(get_db)):
    scheme = nps.get_scheme_with_nav(db, scheme_id)
    if scheme is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Scheme not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return scheme


@router.get("/stock", response_model=list[StockMasterRead])
def search_stock(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return stock_master.search_stocks(db, q, limit)


@router.get("/stock/{master_id}", response_model=StockMasterRead)
def get_stock(master_id: int, db: Session = Depends(get_db)):
    stock = stock_master.get_stock_master(db, master_id)
    if stock is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Stock not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return stock


STOCK_CLOSE_MAX_GAP_DAYS = 7


@router.get("/stock/{master_id}/close", response_model=StockClose)
def get_stock_close(
    master_id: int,
    on_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    """The stock's close on or up to 7 days before a date: the stored daily close, else the newest
    stored close when that falls in the same window. 404 when neither exists."""
    nav_history.validate_not_future(on_date)
    window_start = on_date - timedelta(days=STOCK_CLOSE_MAX_GAP_DAYS)
    closes = stock_history.closes_between(db, [master_id], window_start, on_date).get(master_id)
    if closes:
        price_date, price = closes[-1]
        return {"price": price, "price_date": price_date, "source": "history"}
    latest = stock_prices.latest_prices(db, [master_id]).get(master_id)
    if latest is not None and latest.price_time is not None:
        latest_date = latest.price_time.date()
        if window_start <= latest_date <= on_date:
            return {"price": latest.price, "price_date": latest_date, "source": "latest"}
    raise HTTPException(
        status_code=404,
        detail={
            "message": "Price not available",
            "description": "No close for this stock on or just before this date. Enter the price yourself.",
        },
    )


@router.get("/bond", response_model=list[BondMasterRead])
def search_bond(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return bond_master.search_bonds(db, q, limit)


@router.get("/bond/{master_id}", response_model=BondMasterRead)
def get_bond(master_id: int, db: Session = Depends(get_db)):
    bond = bond_master.get_bond_master(db, master_id)
    if bond is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Bond not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return bond


@router.get("/fd-issuer", response_model=list[FdIssuerRead])
def search_fd_issuer(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    return fd_issuers.search_issuers(db, q, limit)


@router.get("/fd-issuer/{issuer_id}", response_model=FdIssuerRead)
def get_fd_issuer(issuer_id: int, db: Session = Depends(get_db)):
    issuer = fd_issuers.get_issuer(db, issuer_id)
    if issuer is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Issuer not found",
                "description": "The requested resource doesn't exist.",
            },
        )
    return issuer


@router.get("/mf/{scheme_code}/nav",response_model=MFNavOnDate)
def get_mf_nav(
    scheme_code: int,
    on_date: date = Query(alias="date"),
    db: Session = Depends(get_db),
):
    nav_history.validate_not_future(on_date)
    if amfi.get_scheme(db, scheme_code) is None:
        raise HTTPException(status_code=404, detail="Scheme not found")
    try:
        found = nav_history.resolve_nav(db, scheme_code, on_date)
    except nav_history.NavSourceError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Couldn't fetch NAV history",
                "description": "The NAV source is unavailable. Try again shortly.",
            },
        ) from exc
    if found is None:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "NAV not available",
                "description": "No NAV published on or before this date.",
            },
        )
    return {"scheme_code": scheme_code, "requested_date": on_date, **found}


GOLD_RATE_MAX_GAP_DAYS = 7
MAX_OTHER_CATEGORIES = 20


def distinct_categories(rows: list[tuple[str, int]], limit: int = MAX_OTHER_CATEGORIES) -> list[str]:
    """Categories from (category, id) rows: case-insensitive distinct, newest spelling, most used first."""
    counts: dict[str, int] = {}
    newest: dict[str, tuple[int, str]] = {}
    for category, row_id in rows:
        key = category.strip().lower()
        counts[key] = counts.get(key, 0) + 1
        if key not in newest or row_id > newest[key][0]:
            newest[key] = (row_id, category)
    # Most used first; ties go to the more recently used category.
    ordered = sorted(counts, key=lambda k: (-counts[k], -newest[k][0]))
    return [newest[k][1] for k in ordered[:limit]]


@router.get("/other/categories", response_model=list[str])
def other_categories(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(Other.category, Other.id).where(Other.user_id == user.id)).all()
    return distinct_categories([(c, i) for c, i in rows])


@router.get("/gold/rate", response_model=GoldRateOnDate)
def get_gold_rate(
    purity: GoldPurity,
    on_date: date = Query(alias="date"),
    metal: GoldMetal = "gold",
    db: Session = Depends(get_db),
):
    nav_history.validate_not_future(on_date)
    allowed = SILVER_PURITIES if metal == "silver" else GOLD_METAL_PURITIES
    if purity not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "message": GOLD_PURITY_ERROR,
                "description": f"That purity isn't available for {metal}.",
            },
        )
    found = gold_rates.rate_on_or_before(db, metal, purity, on_date)
    if found is None or (on_date - found[1]) > timedelta(days=GOLD_RATE_MAX_GAP_DAYS):
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"{metal.capitalize()} rate not available",
                "description": "No IBJA rate on or just before this date. Enter the amount yourself.",
            },
        )
    rate, rate_date = found
    return {
        "metal": metal,
        "purity": purity,
        "requested_date": on_date,
        "rate_date": rate_date,
        "rate_per_gram": rate,
    }
