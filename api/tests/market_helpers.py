import io
import zipfile
from datetime import date
from pathlib import Path

from app.services.market_files import Sources

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 26)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def by_isin(rows):
    return {r["isin"]: r for r in rows}


def zip_text(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BhavCopy.csv", text)
    return buffer.getvalue()


def make_sources(**overrides) -> Sources:
    base = {
        "equity": read("nse_equity_sample.csv"),
        "etf": read("nse_etf_sample.csv"),
        "debt": read("nse_debt_sample.csv"),
        "bhav": (date(2026, 10, 23), zip_text(read("nse_bhav_sample.csv"))),
        "bse": (date(2026, 10, 23), read("bse_bhav_sample.csv")),
    }
    return Sources(**{**base, **overrides})
