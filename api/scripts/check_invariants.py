"""Read-only invariant check of the data (runs scripts/invariants.sql).

Usage: DATABASE_URL=... python scripts/check_invariants.py   (or pass the URL as the first argument)

Opens one connection, makes the transaction READ ONLY, runs each query of invariants.sql and
prints a count per invariant plus the violating ids. Exit code 1 when anything is violated,
2 when it could not run. It never prints the connection string and never writes.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, make_url

SQL_FILE = Path(__file__).with_name("invariants.sql")
MARKER = re.compile(r"^-- name: (\w+)\s*$", re.MULTILINE)


def load_queries(path: Path = SQL_FILE) -> list[tuple[str, str]]:
    """(name, sql) for each `-- name:` block, comment lines removed."""
    text = path.read_text()
    marks = list(MARKER.finditer(text))
    queries = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = "\n".join(
            line for line in text[mark.end() : end].splitlines() if not line.lstrip().startswith("--")
        ).strip()
        queries.append((mark.group(1), body))
    return queries


def open_readonly(url: str) -> Connection:
    """A connection whose transaction is READ ONLY (any write statement fails)."""
    parsed = make_url(url)
    if parsed.drivername in ("postgresql", "postgres"):
        parsed = parsed.set(drivername="postgresql+psycopg")
    engine = create_engine(parsed, connect_args={"prepare_threshold": None})
    conn = engine.connect()
    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    return conn


def run_checks(conn: Connection) -> dict[str, list[dict]]:
    """Violating rows (as dicts without the name column) per invariant; empty list = holds."""
    results: dict[str, list[dict]] = {}
    for name, sql in load_queries():
        result = conn.exec_driver_sql(sql)
        keys = [k for k in result.keys() if k != "name"]
        results[name] = [dict(zip(keys, row[1:], strict=True)) for row in result.fetchall()]
    return results


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else os.environ.get("DATABASE_URL", "")
    if not url:
        print("No database URL: set DATABASE_URL or pass it as the first argument.")
        return 2
    try:
        conn = open_readonly(url)
        try:
            results = run_checks(conn)
        finally:
            conn.rollback()
            conn.close()
    except Exception as exc:  # never print the message: it can contain the connection string
        print(f"Could not run the checks ({type(exc).__name__}).")
        return 2
    bad = 0
    for name, rows in results.items():
        print(f"{'FAIL' if rows else 'ok  '} {name}: {len(rows)}")
        for row in rows[:20]:
            print("     " + ", ".join(f"{k}={v}" for k, v in row.items()))
        if len(rows) > 20:
            print(f"     ... and {len(rows) - 20} more")
        bad += len(rows)
    print(f"{bad} violation(s) in {len(results)} checks.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
