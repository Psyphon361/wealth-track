import secrets
import urllib.error
from dataclasses import asdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.schemas.mf_scheme import AmfiImportResult
from app.schemas.market_master import MarketImportResult
from app.services import amfi, bond_master, market_files, stock_master

# Mounted outside the X-API-Key router: protected by CRON_SECRET (Vercel sends it as a Bearer token).
router = APIRouter(prefix="/cron", tags=["cron"])


def require_cron_secret(request: Request) -> None:
    expected = settings.cron_secret
    provided = request.headers.get("authorization", "")
    if not expected or not secrets.compare_digest(
        provided.encode(), f"Bearer {expected}".encode()
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/amfi", response_model=AmfiImportResult, dependencies=[Depends(require_cron_secret)])
def refresh_amfi(db: Session = Depends(get_db)):
    try:
        text = amfi.fetch_navall()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Couldn't fetch the AMFI file") from exc
    return amfi.import_navall(db, text)


@router.get(
    "/securities", response_model=MarketImportResult, dependencies=[Depends(require_cron_secret)]
)
def refresh_securities(db: Session = Depends(get_db)):
    today = date.today()
    try:
        sources = market_files.fetch_sources(today)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=502, detail="Couldn't fetch the securities files") from exc
    return {
        "stocks": asdict(stock_master.import_stocks(db, sources, today)),
        "bonds": asdict(bond_master.import_bonds(db, sources, today)),
    }
