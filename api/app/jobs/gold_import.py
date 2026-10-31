"""Fetch the IBJA gold rates and store them: `python -m app.jobs.gold_import`."""

from app.db import SessionLocal, get_engine
from app.services import gold_rates


def main() -> None:
    get_engine()
    parsed = gold_rates.parse_rates(gold_rates.fetch_page())
    with SessionLocal() as session:
        result = gold_rates.import_rates(session, parsed)
    print(
        f"rate_date={result.rate_date} session={result.session} "
        f"rows_upserted={result.rows_upserted}"
    )


if __name__ == "__main__":
    main()
