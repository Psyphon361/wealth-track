"""Fetch NSE/BSE files and refresh the stock and bond masters: `python -m app.jobs.securities_import`."""

import time
from datetime import date

from app.db import SessionLocal, get_engine
from app.services import bond_master, market_files, stock_master


def main() -> None:
    get_engine()
    today = date.today()
    started = time.perf_counter()
    sources = market_files.fetch_sources(today)
    fetched = time.perf_counter()
    with SessionLocal() as session:
        stocks = stock_master.import_stocks(session, sources, today)
        bonds = bond_master.import_bonds(session, sources, today)
    done = time.perf_counter()
    print(f"stocks total={stocks.total} kinds={stocks.kinds} skipped={stocks.skipped}")
    print(f"stocks sources={stocks.sources} bhav_date={stocks.bhav_date} bse_date={stocks.bse_date}")
    print(
        f"stocks inserted={stocks.inserted} updated={stocks.updated} "
        f"unchanged={stocks.unchanged} deactivated={stocks.deactivated} "
        f"last_seen_refreshed={stocks.last_seen_refreshed}"
    )
    print(f"bonds total={bonds.total} skipped={bonds.skipped} sources={bonds.sources} bhav_date={bonds.bhav_date}")
    print(
        f"bonds inserted={bonds.inserted} updated={bonds.updated} "
        f"unchanged={bonds.unchanged} deactivated={bonds.deactivated} "
        f"last_seen_refreshed={bonds.last_seen_refreshed}"
    )
    for label, error in (
        ("bhav_error", stocks.bhav_error or bonds.bhav_error),
        ("bse_error", stocks.bse_error),
    ):
        if error:
            print(f"{label}={error}")
    print(f"fetch={fetched - started:.1f}s import={done - fetched:.1f}s total={done - started:.1f}s")


if __name__ == "__main__":
    main()
