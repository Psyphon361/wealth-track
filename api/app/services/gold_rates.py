"""IBJA gold rates per gram by purity, from https://ibjarates.com/ (IBJA benchmark rates).

The home page lists published rates per 10 g (AM and PM tables, newest date first); we divide by
10. The big "per gram" tiles on the page are truncated to whole rupees, so they are not used.
Rows are keyed by the date the page states, never by today: IBJA does not publish on weekends or
central-govt holidays and the page then keeps showing the last published date. For one date the
PM rate overrides the AM rate.

Latest rates go to `gold_rate_latest` (only if not older than the stored date), every parsed date
to `gold_rate_history`.
"""

import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.gold_rate import GoldRateHistory, GoldRateLatest
from app.schemas.gold import GoldImportResult

SOURCE = "ibja"
URL = "https://ibjarates.com/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
FETCH_TIMEOUT = 30
PURITIES = ("999", "995", "916", "750", "585")
_GRAMS_PER_RATE = Decimal(10)
_CENT = Decimal("0.01")

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_DATE_CELL = re.compile(
    r'data-label="(AM|PM)"[^>]*>\s*<strong>\s*(\d{2}/\d{2}/\d{4})\s*</strong>'
)
_RATE_CELL = re.compile(r'data-label="Gold (\d{3})"[^>]*>\s*([\d,]+(?:\.\d+)?)\s*<')


class GoldRatesError(Exception):
    """The IBJA page could not be parsed (layout changed or rates missing)."""


@dataclass
class ParsedRates:
    rate_date: date
    session: str
    rates: dict[str, Decimal]  # per gram, for rate_date / session
    history: dict[date, dict[str, Decimal]] = field(default_factory=dict)  # every date, PM over AM


def _ssl_context() -> ssl.SSLContext:
    # IBJA's issuer is missing from some system CA stores; prefer certifi's bundle when installed.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def fetch_page() -> str:
    request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    context = _ssl_context()
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT, context=context) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def parse_rates(html: str) -> ParsedRates:
    # (date, session) -> {purity: per gram}
    found: dict[tuple[date, str], dict[str, Decimal]] = {}
    for row in _ROW.findall(html):
        head = _DATE_CELL.search(row)
        if not head:
            continue
        session, text = head.groups()
        rate_date = datetime.strptime(text, "%d/%m/%Y").date()
        rates = {
            purity: (Decimal(value.replace(",", "")) / _GRAMS_PER_RATE).quantize(_CENT)
            for purity, value in _RATE_CELL.findall(row)
        }
        found[(rate_date, session)] = rates
    if not found:
        raise GoldRatesError("No gold rate rows found on the IBJA page")

    history: dict[date, dict[str, Decimal]] = {}
    sessions: dict[date, str] = {}
    for (rate_date, session), rates in sorted(found.items(), key=lambda i: (i[0][0], i[0][1] == "PM")):
        if not all(p in rates for p in PURITIES):
            continue  # a partial row never overrides a full one
        history[rate_date] = {p: rates[p] for p in PURITIES}  # AM first, PM overrides
        sessions[rate_date] = session
    latest = max(found, key=lambda k: k[0])[0]
    if latest not in history:
        missing = [p for p in PURITIES if p not in found.get((latest, "PM"), found.get((latest, "AM"), {}))]
        raise GoldRatesError(f"IBJA page is missing gold purities: {', '.join(missing)}")
    return ParsedRates(latest, sessions[latest], history[latest], history)


def import_rates(session: Session, parsed: ParsedRates) -> GoldImportResult:
    """Upsert history for every parsed date and latest for the newest one. Commits."""
    history = parsed.history or {parsed.rate_date: parsed.rates}
    history_values = [
        {"purity": p, "rate_date": d, "rate_per_gram": rate}
        for d, rates in history.items()
        for p, rate in rates.items()
    ]
    statement = pg_insert(GoldRateHistory).values(history_values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["purity", "rate_date"],
            set_={"rate_per_gram": statement.excluded.rate_per_gram},
        )
    )
    latest_values = [
        {
            "purity": p,
            "rate_per_gram": rate,
            "rate_date": parsed.rate_date,
            "session": parsed.session,
            "source": SOURCE,
            "updated_at": sa.func.now(),
        }
        for p, rate in parsed.rates.items()
    ]
    statement = pg_insert(GoldRateLatest).values(latest_values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["purity"],
            set_={c: statement.excluded[c] for c in latest_values[0] if c != "purity"},
            where=GoldRateLatest.rate_date <= statement.excluded.rate_date,
        )
    )
    session.commit()
    return GoldImportResult(
        rate_date=parsed.rate_date, session=parsed.session, rows_upserted=len(history_values)
    )


def latest_rates(session: Session) -> dict[str, tuple[Decimal, date]]:
    rows = session.scalars(sa.select(GoldRateLatest)).all()
    return {r.purity: (r.rate_per_gram, r.rate_date) for r in rows}


def history_between(
    session: Session, purities: list[str], start: date, end: date
) -> dict[str, list[tuple[date, Decimal]]]:
    """History rows per purity for start <= rate_date <= end, oldest first.

    Callers pick the last row on or before a date (IBJA skips weekends and holidays).
    """
    rows = session.execute(
        sa.select(GoldRateHistory.purity, GoldRateHistory.rate_date, GoldRateHistory.rate_per_gram)
        .where(
            GoldRateHistory.purity.in_(purities),
            GoldRateHistory.rate_date >= start,
            GoldRateHistory.rate_date <= end,
        )
        .order_by(GoldRateHistory.rate_date)
    ).all()
    result: dict[str, list[tuple[date, Decimal]]] = {p: [] for p in purities}
    for purity, rate_date, rate in rows:
        result[purity].append((rate_date, rate))
    return result


def rate_on_or_before(
    session: Session, purity: str, on: date
) -> tuple[Decimal, date] | None:
    row = session.execute(
        sa.select(GoldRateHistory.rate_per_gram, GoldRateHistory.rate_date)
        .where(GoldRateHistory.purity == purity, GoldRateHistory.rate_date <= on)
        .order_by(GoldRateHistory.rate_date.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None
