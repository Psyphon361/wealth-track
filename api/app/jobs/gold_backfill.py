"""One-time, re-runnable backfill of historical IBJA rates into gold_rate_history.

`python -m app.jobs.gold_backfill [--source pdf|wayback|all] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--dry-run]`

Only missing rows are inserted; existing rows and gold_rate_latest are never touched.
--dry-run fetches and parses, prints the rates and writes nothing (it does not read the database).
With --source all the PDF source runs first, then Wayback. A source that fails with a network
error is reported and skipped; the other still runs and the exit code is 1.
"""

import argparse
import sys
import urllib.error
from datetime import date

from app.db import SessionLocal, get_engine
from app.services import gold_history

NETWORK_ERRORS = (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError)


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code} {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=("pdf", "wayback", "all"), default="all")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2014, 1, 1))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.start > args.end:
        parser.error("--from must not be after --to")

    session = None
    if not args.dry_run:
        get_engine()
        session = SessionLocal()
    results: dict[str, gold_history.Stats] = {}
    failed: list[str] = []
    try:
        sources = []
        if args.source in ("pdf", "all"):
            sources.append(("pdf", gold_history.backfill_pdf))
        if args.source in ("wayback", "all"):
            sources.append(("wayback", gold_history.backfill_wayback))
        for name, run in sources:
            try:
                results[name] = run(session, args.start, args.end, dry_run=args.dry_run)
            except NETWORK_ERRORS as exc:
                print(f"{name}: failed after retries: {_describe(exc)}")
                failed.append(name)
    finally:
        if session is not None:
            session.close()

    print("Summary" + (" (dry run, nothing written)" if args.dry_run else ""))
    for name, stats in results.items():
        print(
            f"  {name}: {len(stats.found_full)} dates with full rows, "
            f"{len(stats.found_filled)} filled from the 5-day table, "
            f"{len(stats.missing)} report files missing, {len(stats.unparsed)} unreadable, "
            f"{stats.inserted} rows inserted"
        )
        if stats.missing:
            print(f"    missing files: {', '.join(d.isoformat() for d in stats.missing)}")
        if stats.unparsed:
            print(f"    unreadable files: {', '.join(d.isoformat() for d in stats.unparsed)}")
    if failed:
        print(f"Failed sources: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
