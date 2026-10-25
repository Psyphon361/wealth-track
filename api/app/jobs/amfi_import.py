"""Fetch NAVAll.txt from AMFI and refresh mf_schemes: `python -m app.jobs.amfi_import`."""

import time

from app.db import SessionLocal, get_engine
from app.services import amfi


def main() -> None:
    get_engine()
    started = time.perf_counter()
    text = amfi.fetch_navall()
    fetched = time.perf_counter()
    with SessionLocal() as session:
        result = amfi.import_navall(session, text)
    done = time.perf_counter()
    print(
        f"rows={result.rows} active={result.active} inactive={result.inactive} "
        f"file_date={result.file_date}"
    )
    print(
        f"schemes inserted={result.inserted} updated={result.updated} "
        f"unchanged={result.unchanged} deactivated={result.deactivated} "
        f"navs_upserted={result.navs_upserted} history_appended={result.history_appended}"
    )
    print(f"fetch={fetched - started:.1f}s import={done - fetched:.1f}s total={done - started:.1f}s")


if __name__ == "__main__":
    main()
