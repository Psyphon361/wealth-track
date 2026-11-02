"""Permanently remove holdings deleted more than 30 days ago: `python -m app.jobs.purge_deleted`."""

from app.db import SessionLocal, get_engine
from app.services import purge


def main() -> None:
    get_engine()
    with SessionLocal() as session:
        counts = purge.purge_deleted(session)
    print(" ".join(f"{slug}={n}" for slug, n in counts.items()))


if __name__ == "__main__":
    main()
