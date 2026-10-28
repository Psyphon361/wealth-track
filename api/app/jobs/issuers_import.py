"""Fetch bank lists and refresh the FD/RD issuer master: `python -m app.jobs.issuers_import`."""

import time
from datetime import date

from app.db import SessionLocal, get_engine
from app.services import fd_issuers


def main() -> None:
    get_engine()
    started = time.perf_counter()
    sources = fd_issuers.fetch_sources()
    fetched = time.perf_counter()
    with SessionLocal() as session:
        result = fd_issuers.import_issuers(session, sources, date.today())
    done = time.perf_counter()
    print(f"issuers total={result.total} skipped={result.skipped}")
    print(f"issuers by_category={result.by_category}")
    print(f"issuers by_source={result.by_source}")
    print(
        f"issuers inserted={result.inserted} updated={result.updated} "
        f"unchanged={result.unchanged} deactivated={result.deactivated} "
        f"last_seen_refreshed={result.last_seen_refreshed} merge_links_updated={result.merge_links_updated}"
    )
    print(
        f"dicgc names={result.dicgc_names} matched={result.dicgc_matched} "
        f"unmatched_banks={result.dicgc_unmatched} unclaimed_names={result.dicgc_unclaimed}"
    )
    for category, names in result.unmatched_names.items():
        print(f"dicgc unmatched {category} ({len(names)}): {names}")
    if result.unclaimed_names:
        print(f"dicgc unclaimed (first {len(result.unclaimed_names)}): {result.unclaimed_names}")
    for tag, error in result.errors.items():
        print(f"{tag}_error={error}")
    for note in result.notes:
        print(f"note: {note}")
    print(f"fetch={fetched - started:.1f}s import={done - fetched:.1f}s total={done - started:.1f}s")


if __name__ == "__main__":
    main()
