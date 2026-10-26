"""Fetch NSE/BSE files and refresh the securities master: `python -m app.jobs.securities_import`."""

import time
from datetime import date

from app.db import SessionLocal, get_engine
from app.services import securities


def main() -> None:
    get_engine()
    today = date.today()
    started = time.perf_counter()
    sources = securities.fetch_sources(today)
    fetched = time.perf_counter()
    with SessionLocal() as session:
        result = securities.import_securities(session, sources, today)
    done = time.perf_counter()
    print(f"total={result.total} kinds={result.kinds} skipped={result.skipped}")
    print(f"sources={result.sources} bhav_date={result.bhav_date} bse_date={result.bse_date}")
    print(
        f"securities inserted={result.inserted} updated={result.updated} "
        f"unchanged={result.unchanged} deactivated={result.deactivated} "
        f"last_seen_refreshed={result.last_seen_refreshed}"
    )
    if result.bhav_error:
        print(f"bhav_error={result.bhav_error}")
    if result.bse_error:
        print(f"bse_error={result.bse_error}")
    print(f"fetch={fetched - started:.1f}s import={done - fetched:.1f}s total={done - started:.1f}s")


if __name__ == "__main__":
    main()
