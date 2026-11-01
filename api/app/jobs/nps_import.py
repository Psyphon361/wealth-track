"""Fetch the NPS Trust NAV report and refresh nps_master: `python -m app.jobs.nps_import`."""

import time

from app.db import SessionLocal, get_engine
from app.services import nps


def main() -> None:
    get_engine()
    started = time.perf_counter()
    text = nps.fetch_latest()
    fetched = time.perf_counter()
    with SessionLocal() as session:
        result = nps.import_latest(session, nps.parse_latest(text))
    done = time.perf_counter()
    print(
        f"rows={result.rows} active={result.active} inactive={result.inactive} "
        f"file_date={result.file_date}"
    )
    print(
        f"schemes inserted={result.inserted} updated={result.updated} "
        f"unchanged={result.unchanged} deactivated={result.deactivated} "
        f"navs_upserted={result.navs_upserted} history_appended={result.history_appended} "
        f"history_synced={result.history_synced}"
    )
    print(f"fetch={fetched - started:.1f}s import={done - fetched:.1f}s total={done - started:.1f}s")


if __name__ == "__main__":
    main()
