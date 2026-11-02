"""One-off: copy missing gold_rate_history rows from a source DB to a target DB.

    SOURCE_DATABASE_URL=... TARGET_DATABASE_URL=... python -m app.jobs.copy_gold_history [--apply]

Inserts only (INSERT ... ON CONFLICT DO NOTHING); never updates or deletes, and touches no other
table. Without --apply nothing is written (dry run). Connection URLs are never printed.
"""

import argparse
import os
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.jobs.copy_holdings import _engine
from app.models.gold_rate import GoldRateHistory

BATCH_SIZE = 1000
KEY_FIELDS = ("metal", "purity", "rate_date")
COLUMNS = KEY_FIELDS + ("rate_per_gram",)


# ---- pure logic (no DB) ----------------------------------------------------------------


def urls_equal(source_url: str, target_url: str) -> bool:
    return source_url.strip() == target_url.strip()


def row_key(row: dict[str, Any]) -> tuple:
    return tuple(row[k] for k in KEY_FIELDS)


def missing_rows(source_rows: Iterable[dict[str, Any]], target_keys: set[tuple]) -> list[dict[str, Any]]:
    """Source rows whose (metal, purity, rate_date) key is not in the target."""
    return [r for r in source_rows if row_key(r) not in target_keys]


def counts_by_year(rows: Iterable[dict[str, Any]]) -> dict[int, int]:
    counter = Counter(r["rate_date"].year for r in rows)
    return dict(sorted(counter.items()))


def batches(rows: Sequence[dict[str, Any]], size: int = BATCH_SIZE) -> Iterator[list[dict[str, Any]]]:
    for i in range(0, len(rows), size):
        yield list(rows[i : i + size])


def build_insert_statement():
    """INSERT ... ON CONFLICT (metal, purity, rate_date) DO NOTHING for gold_rate_history."""
    return pg_insert(GoldRateHistory.__table__).on_conflict_do_nothing(index_elements=list(KEY_FIELDS))


# ---- I/O -------------------------------------------------------------------------------


def _read_rows(session: Session) -> list[dict[str, Any]]:
    cols = [getattr(GoldRateHistory, c) for c in COLUMNS]
    return [dict(zip(COLUMNS, r)) for r in session.execute(select(*cols)).all()]


def _count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(GoldRateHistory)) or 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy missing gold_rate_history rows source -> target")
    parser.add_argument("--apply", action="store_true", help="write to the target (default: dry run)")
    args = parser.parse_args()

    source_url = os.environ.get("SOURCE_DATABASE_URL", "")
    target_url = os.environ.get("TARGET_DATABASE_URL", "")
    if not source_url or not target_url:
        sys.exit("SOURCE_DATABASE_URL and TARGET_DATABASE_URL must both be set")
    if urls_equal(source_url, target_url):
        sys.exit("Source and target are the same database; refusing to run")

    source_engine = _engine(source_url)
    target_engine = _engine(target_url)
    try:
        with Session(source_engine) as source, Session(target_engine) as target:
            source_rows = _read_rows(source)
            target_keys = {row_key(r) for r in _read_rows(target)}
            todo = missing_rows(source_rows, target_keys)
            print(f"Source rows: {len(source_rows)}; target rows: {len(target_keys)}")
            print(f"Rows to insert: {len(todo)}")
            for year, n in counts_by_year(todo).items():
                print(f"  {year}: {n}")

            if not args.apply:
                print("Dry run: nothing written. Re-run with --apply to insert.")
                return
            if not todo:
                print("Nothing to insert.")
                return

            before = _count(target)
            stmt = build_insert_statement()
            for chunk in batches(todo):
                target.execute(stmt, chunk)
            target.commit()
            after = _count(target)
            print(f"Inserted {after - before} rows (target now {after}).")
    finally:
        source_engine.dispose()
        target_engine.dispose()


if __name__ == "__main__":
    main()
