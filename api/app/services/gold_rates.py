"""IBJA gold and silver rates per gram, from https://ibjarates.com/ (IBJA benchmark rates).

The home page lists published rates (AM and PM tables, newest date first): gold per 10 g by
purity (divided by 10) and Silver 999 per kg (divided by 1000). The big "per gram" tiles on the
page are truncated to whole rupees, so they are not used. Rates are keyed by (metal, purity).
IBJA publishes only silver 999; silver 925 is never stored and is derived as 999 x 925 / 999
(rate x 925 / 999, rounded to 0.01) by the read helpers. A row without silver still imports gold.
Rows are keyed by the date the page states, never by today: IBJA does not publish on weekends or
central-govt holidays and the page then keeps showing the last published date. For one date the
PM rate overrides the AM rate.

Latest rates go to `gold_rate_latest` (only if not older than the stored date), every parsed date
to `gold_rate_history`.
"""

import json
import re
import ssl
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html import unescape

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
METALS = ("gold", "silver")
PURITIES = ("999", "995", "916", "750", "585")  # gold purities
SILVER_PURITIES = ("999", "925")
SILVER_STORED = "999"  # the only silver purity IBJA publishes
_GRAMS_PER_RATE = {"gold": Decimal(10), "silver": Decimal(1000)}
Key = tuple[str, str]  # (metal, purity)
_CENT = Decimal("0.01")

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_DATE_CELL = re.compile(
    r'data-label="(AM|PM)"[^>]*>\s*<strong>\s*(\d{2}/\d{2}/\d{4})\s*</strong>'
)
_RATE_CELL = re.compile(
    r'data-label="(Gold|Silver) (\d{3})"[^>]*>\s*([\d,]+(?:\.\d+)?)\s*<'
)


class GoldRatesError(Exception):
    """The IBJA page could not be parsed (layout changed or rates missing)."""


@dataclass
class ParsedRates:
    rate_date: date
    session: str
    rates: dict[Key, Decimal]  # per gram, for rate_date / session
    history: dict[date, dict[Key, Decimal]] = field(default_factory=dict)  # every date, PM over AM
    # hidden-field PM rates (gold 999/916, silver 999); insert-if-missing only, never "latest"
    backfill: dict[date, dict[Key, Decimal]] = field(default_factory=dict)


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
    # (date, session) -> {(metal, purity): per gram}
    found: dict[tuple[date, str], dict[Key, Decimal]] = {}
    for row in _ROW.findall(html):
        head = _DATE_CELL.search(row)
        if not head:
            continue
        session, text = head.groups()
        rate_date = datetime.strptime(text, "%d/%m/%Y").date()
        rates: dict[Key, Decimal] = {}
        for label, purity, value in _RATE_CELL.findall(row):
            metal = label.lower()
            rates[(metal, purity)] = (
                Decimal(value.replace(",", "")) / _GRAMS_PER_RATE[metal]
            ).quantize(_CENT)
        found[(rate_date, session)] = rates
    if not found:
        raise GoldRatesError("No gold rate rows found on the IBJA page")

    gold_keys = [("gold", p) for p in PURITIES]
    silver_key = ("silver", SILVER_STORED)
    history: dict[date, dict[Key, Decimal]] = {}
    sessions: dict[date, str] = {}
    for (rate_date, session), rates in sorted(found.items(), key=lambda i: (i[0][0], i[0][1] == "PM")):
        if not all(k in rates for k in gold_keys):
            continue  # a partial gold row never overrides a full one
        day = history.setdefault(rate_date, {})
        day.update({k: rates[k] for k in gold_keys})  # AM first, PM overrides
        if silver_key in rates:
            day[silver_key] = rates[silver_key]
        sessions[rate_date] = session
    latest = max(found, key=lambda k: k[0])[0]
    if latest not in history:
        row = found.get((latest, "PM"), found.get((latest, "AM"), {}))
        missing = [p for p in PURITIES if ("gold", p) not in row]
        raise GoldRatesError(f"IBJA page is missing gold purities: {', '.join(missing)}")
    return ParsedRates(latest, sessions[latest], history[latest], history, _parse_backfill(html))


# Hidden page fields: JSON with "labels" (dd/mm/yyyy) and one rate array per series, PM rates.
# Gold is per 10 g, silver per kg (same units as the tables).
_HIDDEN_SERIES = {
    "HdnGold": {"purity999": ("gold", "999"), "purity916": ("gold", "916")},
    "HdnSilver": {"silverRate": ("silver", "999")},
}
_HIDDEN_FIELD = r'<input[^>]*\bname="%s"[^>]*\bvalue="([^"]*)"'


def _parse_backfill(html: str) -> dict[date, dict[Key, Decimal]]:
    """Per-gram rates from the hidden HdnGold / HdnSilver fields. Best effort: never raises."""
    out: dict[date, dict[Key, Decimal]] = {}
    for field_name, series in _HIDDEN_SERIES.items():
        try:
            match = re.search(_HIDDEN_FIELD % field_name, html)
            if not match:
                continue
            data = json.loads(unescape(match.group(1)))
            labels = data["labels"]
            field_rates: dict[date, dict[Key, Decimal]] = {}
            for name, key in series.items():
                values = data[name]
                if len(values) != len(labels):
                    raise ValueError("labels and values differ in length")
                for label, value in zip(labels, values):
                    if value is None:
                        continue
                    day = datetime.strptime(label, "%d/%m/%Y").date()
                    rate = (Decimal(str(value)) / _GRAMS_PER_RATE[key[0]]).quantize(_CENT)
                    if rate <= 0:
                        raise ValueError("non-positive rate")
                    field_rates.setdefault(day, {})[key] = rate
        except (ValueError, KeyError, TypeError, ArithmeticError, AttributeError):
            continue  # a malformed field is skipped whole
        for day, rates in field_rates.items():
            out.setdefault(day, {}).update(rates)
    return out


def import_rates(session: Session, parsed: ParsedRates) -> GoldImportResult:
    """Upsert history for every parsed date and latest for the newest one. Commits.

    Backfill rows (hidden page fields) only fill missing history rows; they never overwrite a
    stored rate and never touch `gold_rate_latest`.
    """
    history = parsed.history or {parsed.rate_date: parsed.rates}
    history_values = [
        {"metal": m, "purity": p, "rate_date": d, "rate_per_gram": rate}
        for d, rates in history.items()
        for (m, p), rate in rates.items()
    ]
    statement = pg_insert(GoldRateHistory).values(history_values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["metal", "purity", "rate_date"],
            set_={"rate_per_gram": statement.excluded.rate_per_gram},
        )
    )
    backfill_values = [
        {"metal": m, "purity": p, "rate_date": d, "rate_per_gram": rate}
        for d, rates in parsed.backfill.items()
        for (m, p), rate in rates.items()
    ]
    if backfill_values:
        session.execute(
            pg_insert(GoldRateHistory)
            .values(backfill_values)
            .on_conflict_do_nothing(index_elements=["metal", "purity", "rate_date"])
        )
    latest_values = [
        {
            "metal": m,
            "purity": p,
            "rate_per_gram": rate,
            "rate_date": parsed.rate_date,
            "session": parsed.session,
            "source": SOURCE,
            "updated_at": sa.func.now(),
        }
        for (m, p), rate in parsed.rates.items()
    ]
    statement = pg_insert(GoldRateLatest).values(latest_values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["metal", "purity"],
            set_={
                c: statement.excluded[c] for c in latest_values[0] if c not in ("metal", "purity")
            },
            where=GoldRateLatest.rate_date <= statement.excluded.rate_date,
        )
    )
    session.commit()
    return GoldImportResult(
        rate_date=parsed.rate_date,
        session=parsed.session,
        rows_upserted=len(history_values),
        backfill_rows=len(backfill_values),
    )


def _stored_key(metal: str, purity: str) -> Key:
    """The stored (metal, purity) a lookup reads: silver 925 comes from silver 999."""
    return (metal, SILVER_STORED) if (metal, purity) == ("silver", "925") else (metal, purity)


def _scaled(metal: str, purity: str, rate: Decimal) -> Decimal:
    """Rate for the requested purity from the stored one (silver 925 = 999 x 925 / 999)."""
    if (metal, purity) == ("silver", "925"):
        return (rate * 925 / 999).quantize(_CENT)
    return rate


def latest_rates(session: Session) -> dict[Key, tuple[Decimal, date]]:
    rows = session.scalars(sa.select(GoldRateLatest)).all()
    out: dict[Key, tuple[Decimal, date]] = {(r.metal, r.purity): (r.rate_per_gram, r.rate_date) for r in rows}
    base = out.get(("silver", SILVER_STORED))
    if base is not None:
        out[("silver", "925")] = (_scaled("silver", "925", base[0]), base[1])
    return out


def previous_rates(session: Session, keys: Iterable[Key]) -> dict[Key, tuple[date, Decimal]]:
    """Per (metal, purity), the stored rate on the latest date strictly before its latest rate date.

    One query over `gold_rate_history` joined to `gold_rate_latest`, DB only. Silver 925 is
    derived from silver 999 like every other read. Keys without such a row are omitted.
    """
    wanted = list(dict.fromkeys(keys))
    if not wanted:
        return {}
    stored = sorted({_stored_key(m, p) for m, p in wanted})
    ranked = (
        sa.select(
            GoldRateHistory.metal.label("metal"),
            GoldRateHistory.purity.label("purity"),
            GoldRateHistory.rate_date.label("rate_date"),
            GoldRateHistory.rate_per_gram.label("rate"),
            sa.func.row_number()
            .over(
                partition_by=(GoldRateHistory.metal, GoldRateHistory.purity),
                order_by=GoldRateHistory.rate_date.desc(),
            )
            .label("rn"),
        )
        .join(
            GoldRateLatest,
            sa.and_(
                GoldRateLatest.metal == GoldRateHistory.metal,
                GoldRateLatest.purity == GoldRateHistory.purity,
            ),
        )
        .where(
            sa.tuple_(GoldRateHistory.metal, GoldRateHistory.purity).in_(stored),
            GoldRateHistory.rate_date < GoldRateLatest.rate_date,
        )
        .subquery()
    )
    rows = session.execute(
        sa.select(ranked.c.metal, ranked.c.purity, ranked.c.rate_date, ranked.c.rate).where(
            ranked.c.rn == 1
        )
    ).all()
    by_stored = {(m, p): (d, r) for m, p, d, r in rows}
    out: dict[Key, tuple[date, Decimal]] = {}
    for metal, purity in wanted:
        hit = by_stored.get(_stored_key(metal, purity))
        if hit is not None:
            out[(metal, purity)] = (hit[0], _scaled(metal, purity, hit[1]))
    return out


def history_between(
    session: Session, keys: list[Key], start: date, end: date
) -> dict[Key, list[tuple[date, Decimal]]]:
    """History rows per (metal, purity) for start <= rate_date <= end, oldest first.

    Callers pick the last row on or before a date (IBJA skips weekends and holidays).
    """
    stored = sorted({_stored_key(m, p) for m, p in keys})
    rows = session.execute(
        sa.select(
            GoldRateHistory.metal,
            GoldRateHistory.purity,
            GoldRateHistory.rate_date,
            GoldRateHistory.rate_per_gram,
        )
        .where(
            sa.tuple_(GoldRateHistory.metal, GoldRateHistory.purity).in_(stored),
            GoldRateHistory.rate_date >= start,
            GoldRateHistory.rate_date <= end,
        )
        .order_by(GoldRateHistory.rate_date)
    ).all()
    by_stored: dict[Key, list[tuple[date, Decimal]]] = {k: [] for k in stored}
    for metal, purity, rate_date, rate in rows:
        by_stored[(metal, purity)].append((rate_date, rate))
    return {
        (m, p): [(d, _scaled(m, p, r)) for d, r in by_stored[_stored_key(m, p)]] for m, p in keys
    }


def rate_on_or_before(
    session: Session, metal: str, purity: str, on: date
) -> tuple[Decimal, date] | None:
    m, p = _stored_key(metal, purity)
    row = session.execute(
        sa.select(GoldRateHistory.rate_per_gram, GoldRateHistory.rate_date)
        .where(
            GoldRateHistory.metal == m,
            GoldRateHistory.purity == p,
            GoldRateHistory.rate_date <= on,
        )
        .order_by(GoldRateHistory.rate_date.desc())
        .limit(1)
    ).first()
    return (_scaled(metal, purity, row[0]), row[1]) if row else None
