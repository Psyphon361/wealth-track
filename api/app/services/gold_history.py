"""One-time backfill of historical IBJA gold and silver rates into `gold_rate_history`.

Two sources:

1. ibja.co daily report PDFs (May 2022 onwards). The report named for date D carries the rates of
   the PREVIOUS trading day, so every row is keyed by the rate date printed inside the PDF ("as of"
   line, else the first row of the spot table), never by the filename date. Page 1 has AM and PM
   tables (gold 999/995/916/750/585 per 10 g, Silver 999 per kg; PM wins over AM) and a table of the
   last 4-5 days of PM rates for gold 999 and silver 999. Dates whose own report is missing are
   filled from that table (gold 999 and silver 999 only), and only when no full row exists.
2. A Wayback Machine snapshot of ibjarates.com (1 Jan 2014 to 14 Feb 2018): one daily table of
   gold 999 and silver 999 (AM and PM). The other gold purities are derived from 999 with fixed
   ratios measured on the 2022+ PDF data (`WAYBACK_RATIOS`).

Rates are stored per gram, quantized to 0.01, like `gold_rates.parse_rates`. Inserts are
`ON CONFLICT DO NOTHING`: existing rows are never overwritten and `gold_rate_latest` is untouched.
"""

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pypdfium2
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.gold_rate import GoldRateHistory
from app.services.gold_rates import (
    _CENT,
    _GRAMS_PER_RATE,
    FETCH_TIMEOUT,
    PURITIES,
    SILVER_STORED,
    USER_AGENT,
    Key,
    _ssl_context,
)

PDF_BASE = "https://ibja.co/Upload/"
PDF_FIRST_DATE = date(2022, 5, 10)  # first report on ibja.co
WAYBACK_URL = "https://web.archive.org/web/20180214id_/https://ibjarates.com/"
WAYBACK_FIRST_DATE = date(2014, 1, 1)
WAYBACK_LAST_DATE = date(2018, 2, 14)
REQUEST_PAUSE = 1.0  # seconds between requests
RETRIES = 4  # attempts per URL on 429 / 5xx / network errors
MAX_RATE_AGE = 5  # a report's rate date is at most this many days before the report date
MAX_SPOT_AGE = 10  # so is every row of its 5-day table
PURITY_TOLERANCE = Decimal("0.01")  # a purity further than 1% from 999 x ratio is a typo
GOLD_KEYS = [("gold", p) for p in PURITIES]
SILVER_KEY = ("silver", SILVER_STORED)

# Ratio of each gold purity to 999 (per-10 g rupee rate), measured on the 2022-2026 PDF data.
WAYBACK_RATIOS: dict[str, Decimal] = {
    "995": Decimal("0.99600"),
    "916": Decimal("0.91600"),
    "750": Decimal("0.75000"),
    "585": Decimal("0.58500"),
}

# File name patterns, tried in order ({a} = DD-MM-YYYY). A sweep of every weekday from 10 May 2022
# to 2 Nov 2026 found only these four (about 70% / 24% / 7% / 2%); underscore-date and
# "IBJA Bullion" (no underscore) variants were probed too and never exist.
_NAME_VARIANTS = (
    "IBJA_Bullion Daily Report - {a}.pdf",
    "IBJA_Bullion Daily Report -{a}.pdf",
    "IBJA_Bullion Daily Report {a}.pdf",
    "IBJA_Bullion Daily Report - {a} .pdf",
)

_ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)"
_SPLIT_ORDINAL = re.compile(r"(\d)\s*[\r\n]+\s*(st|nd|rd|th)\b")
_REPORT_DATE = re.compile(rf"Report Date:\s*{_ORDINAL} ([A-Za-z]+) (\d{{4}})")
_AS_OF = re.compile(rf"as of {_ORDINAL} ([A-Za-z]+) (\d{{4}})")
_SPOT_ROW = re.compile(rf"^{_ORDINAL} ([A-Za-z]+) (\d{{4}}) (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)$")
_RATE_ROW = re.compile(r"^(Gold|Silver) (\d{3}) (\d+(?:\.\d+)?) (\d+(?:\.\d+)?)$")
_WAYBACK_ROW = re.compile(r'<th scope="row">\s*(\d{2} \w{3} \d{4}) \(\w+\)\s*</th>(.*?)</tr>', re.S)
_WAYBACK_CELL = re.compile(r"<td[^>]*>\s*(.*?)\s*</td>", re.S)


class GoldHistoryError(Exception):
    """A report could not be parsed."""


@dataclass
class Report:
    rate_date: date
    full: dict[Key, Decimal]  # per gram, PM over AM; complete gold row (+ silver 999 if printed)
    spot: dict[date, dict[Key, Decimal]] = field(default_factory=dict)  # 4-5 day PM table


@dataclass
class Stats:
    found_full: set[date] = field(default_factory=set)
    found_filled: set[date] = field(default_factory=set)
    missing: list[date] = field(default_factory=list)  # file dates with no report at any URL
    unparsed: list[date] = field(default_factory=list)  # file dates whose PDF could not be read
    inserted: int = 0


def pdf_url_candidates(file_date: date) -> list[str]:
    """URLs to try, in order, for the report named for `file_date`."""
    a = file_date.strftime("%d-%m-%Y")
    return [PDF_BASE + urllib.parse.quote(v.format(a=a)) for v in _NAME_VARIANTS]


def _per_gram(metal: str, value: str) -> Decimal:
    return (Decimal(value) / _GRAMS_PER_RATE[metal]).quantize(_CENT)


def _try_date(day: str, month: str, year: str) -> date | None:
    try:
        return datetime.strptime(f"{day} {month} {year}", "%d %B %Y").date()
    except ValueError:
        return None


def pdf_text(data: bytes) -> str:
    """Text of page 1 of a report PDF."""
    document = pypdfium2.PdfDocument(data)
    try:
        return document[0].get_textpage().get_text_range()
    finally:
        document.close()


def parse_report_text(text: str) -> Report:
    """Parse page-1 text of a daily report. The rate date is the one printed, not the file's."""
    text = _SPLIT_ORDINAL.sub(r"\1\2", text)  # some PDFs extract "9\nth June" for "9th June"
    report_match = _REPORT_DATE.search(text)
    report_date = _try_date(*report_match.groups()) if report_match else None

    def plausible(day: date | None, max_age: int) -> bool:
        if day is None:
            return False
        return report_date is None or 0 < (report_date - day).days <= max_age

    am_pm: dict[Key, tuple[str, str]] = {}
    spot: dict[date, dict[Key, Decimal]] = {}
    spot_order: list[date] = []
    for line in (line.strip() for line in text.splitlines()):
        row = _RATE_ROW.match(line)
        if row:
            label, purity, am, pm = row.groups()
            am_pm.setdefault((label.lower(), purity), (am, pm))
            continue
        row = _SPOT_ROW.match(line)
        if row:
            day, month, year, gold, silver = row.groups()
            spot_date = _try_date(day, month, year)
            if plausible(spot_date, MAX_SPOT_AGE) and spot_date not in spot:  # typo'd dates are dropped
                spot_order.append(spot_date)
                spot[spot_date] = {
                    ("gold", "999"): _per_gram("gold", gold),
                    SILVER_KEY: _per_gram("silver", silver),
                }

    full: dict[Key, Decimal] = {}
    for (metal, purity), (am, pm) in am_pm.items():
        if metal == "silver" and purity != SILVER_STORED:
            continue
        chosen = pm if Decimal(pm) > 0 else am  # PM over AM
        if Decimal(chosen) > 0:
            full[(metal, purity)] = _per_gram(metal, chosen)
    if not all(k in full for k in GOLD_KEYS):
        full = {}  # a partial gold row is never a full row
    else:
        derived = derive_gold_purities({("gold", "999"): full[("gold", "999")]})
        for key, value in derived.items():
            if key != ("gold", "999") and abs(full[key] / value - 1) > PURITY_TOLERANCE:
                full[key] = value  # the PDF has typos such as 506743 for 50674

    # The printed dates have typos too ("as of 11th April" on a May report), so each candidate
    # must fall within a few days before the report date. The spot table's top row wins when its
    # gold rate equals the PM gold 999 rate; the "as of" line is next.
    as_of_match = _AS_OF.search(text)
    as_of = _try_date(*as_of_match.groups()) if as_of_match else None
    top = spot_order[0] if spot_order else None
    gold_999 = full.get(("gold", "999"))
    if top is not None and (gold_999 is None or spot[top][("gold", "999")] == gold_999):
        rate_date = top
    elif plausible(as_of, MAX_RATE_AGE):
        rate_date = as_of
    elif top is not None:
        rate_date = top
    else:
        raise GoldHistoryError("No plausible rate date found in the report")
    return Report(rate_date, full, spot)


def parse_wayback(html: str) -> dict[date, dict[Key, Decimal]]:
    """Gold 999 and silver 999 per gram per date, PM over AM. Blank cells (no rate) are skipped."""
    out: dict[date, dict[Key, Decimal]] = {}
    for text, body in _WAYBACK_ROW.findall(html):
        cells = _WAYBACK_CELL.findall(body)
        if len(cells) != 4:
            continue
        gold_am, gold_pm, silver_am, silver_pm = cells
        day: dict[Key, Decimal] = {}
        gold = gold_pm or gold_am
        silver = silver_pm or silver_am
        if gold.isdigit() and int(gold) > 0:
            day[("gold", "999")] = _per_gram("gold", gold)
        if silver.isdigit() and int(silver) > 0:
            day[SILVER_KEY] = _per_gram("silver", silver)
        if day:
            out[datetime.strptime(text, "%d %b %Y").date()] = day
    return out


def derive_gold_purities(
    day: dict[Key, Decimal], ratios: dict[str, Decimal] = WAYBACK_RATIOS
) -> dict[Key, Decimal]:
    """Add 995/916/750/585 to a gold 999 rate: whole rupees per 10 g, then per gram at 0.01."""
    base = day.get(("gold", "999"))
    if base is None:
        return day
    out = dict(day)
    for purity, ratio in ratios.items():
        per_10g = (base * 10 * ratio).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        out[("gold", purity)] = (per_10g / 10).quantize(_CENT)
    return out


def _fetch(url: str) -> bytes | None:
    """Body of the URL, or None on 404. Other failures raise."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT, context=_ssl_context()) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code not in (429, 500, 502, 503, 504) or attempt == RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == RETRIES:
                raise
        time.sleep(15 * attempt)  # rate limited or flaky: back off, then retry
    return None


Fetcher = Callable[[str], bytes | None]


def fetch_report(
    file_date: date, fetch: Fetcher = _fetch, pause: Callable[[float], None] = time.sleep
) -> bytes | None:
    """PDF bytes for the report named for `file_date`, trying each filename variant in order."""
    for url in pdf_url_candidates(file_date):
        body = fetch(url)
        pause(REQUEST_PAUSE)
        if body is not None and body.startswith(b"%PDF"):
            return body
    return None


def _month_batches(start: date, end: date) -> Iterator[tuple[date, date]]:
    cursor = start
    while cursor <= end:
        month_end = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        yield cursor, min(month_end, end)
        cursor = month_end + timedelta(days=1)


def _previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def full_gold_dates(session: Session, start: date, end: date) -> set[date]:
    """Dates in [start, end] that already have all five gold purities in history."""
    rows = session.execute(
        sa.select(GoldRateHistory.rate_date)
        .where(
            GoldRateHistory.metal == "gold",
            GoldRateHistory.purity.in_(PURITIES),
            GoldRateHistory.rate_date >= start,
            GoldRateHistory.rate_date <= end,
        )
        .group_by(GoldRateHistory.rate_date)
        .having(sa.func.count() == len(PURITIES))
    ).all()
    return {r[0] for r in rows}


def insert_missing(session: Session, rows: dict[date, dict[Key, Decimal]]) -> int:
    """INSERT ... ON CONFLICT DO NOTHING for every (metal, purity, date). Commits. Returns rows added."""
    values = [
        {"metal": m, "purity": p, "rate_date": d, "rate_per_gram": rate}
        for d, rates in rows.items()
        for (m, p), rate in rates.items()
    ]
    if not values:
        return 0
    result = session.execute(
        pg_insert(GoldRateHistory)
        .values(values)
        .on_conflict_do_nothing(index_elements=["metal", "purity", "rate_date"])
    )
    session.commit()
    return result.rowcount or 0


def _print_day(source: str, day: date, rates: dict[Key, Decimal], tag: str) -> None:
    parts = []
    for (metal, purity), rate in sorted(rates.items()):
        scaled = rate * _GRAMS_PER_RATE[metal]
        unit = "/kg" if metal == "silver" else "/10g"
        parts.append(f"{metal} {purity}={scaled.quantize(Decimal(1))}{unit} ({rate}/g)")
    print(f"  [{source}{tag}] {day}: " + "; ".join(parts))


def backfill_pdf(
    session: Session | None,
    start: date,
    end: date,
    *,
    dry_run: bool = False,
    fetch: Fetcher = _fetch,
    pause: Callable[[float], None] = time.sleep,
    today: date | None = None,
) -> Stats:
    """Backfill rate dates in [start, end] from the daily report PDFs, one commit per month.

    A report named for D holds the previous trading day's rates, so files up to 4 days after `end`
    are fetched too; only rate dates inside [start, end] are kept. Report dates whose previous
    weekday already has a full gold row are skipped (nothing to learn). `dry_run` ignores the
    database, writes nothing and prints what it parsed.
    """
    stats = Stats()
    today = today or date.today()
    start = max(start, PDF_FIRST_DATE)
    last_file = min(end + timedelta(days=4), today)
    for batch_start, batch_end in _month_batches(start, last_file):
        done: set[date] = set()
        if session is not None and not dry_run:
            done = full_gold_dates(session, batch_start - timedelta(days=4), batch_end)
        full: dict[date, dict[Key, Decimal]] = {}
        fills: dict[date, dict[Key, Decimal]] = {}
        file_date = batch_start
        while file_date <= batch_end:
            if file_date.weekday() < 5 and _previous_weekday(file_date) not in done:
                body = fetch_report(file_date, fetch, pause)
                if body is None:
                    stats.missing.append(file_date)
                else:
                    try:
                        report = parse_report_text(pdf_text(body))
                    except (GoldHistoryError, pypdfium2.PdfiumError, ValueError):
                        stats.unparsed.append(file_date)
                    else:
                        if report.full and start <= report.rate_date <= end:
                            full.setdefault(report.rate_date, report.full)
                        for spot_date, rates in report.spot.items():
                            if start <= spot_date <= end:
                                fills.setdefault(spot_date, rates)
            file_date += timedelta(days=1)

        filled = {
            d: r
            for d, r in fills.items()
            if d not in full and d not in done and d not in stats.found_full
        }
        rows = {**filled, **full}
        for d in sorted(rows):
            if dry_run:
                _print_day("pdf", d, rows[d], "" if d in full else " 5-day-table")
        stats.found_full |= set(full)
        stats.found_filled |= set(filled)
        added = 0
        if session is not None and not dry_run:
            added = insert_missing(session, rows)
            stats.inserted += added
        print(
            f"pdf {batch_start:%Y-%m}: {len(full)} full, {len(filled)} filled, "
            f"{added} rows inserted"
        )
    return stats


def backfill_wayback(
    session: Session | None,
    start: date,
    end: date,
    *,
    dry_run: bool = False,
    fetch: Fetcher = _fetch,
    ratios: dict[str, Decimal] | None = None,
) -> Stats:
    """Backfill [start, end] from the Wayback snapshot. Gold 999 and silver 999; other gold
    purities derived from 999 with `ratios` (default `WAYBACK_RATIOS`; empty dict = 999 only)."""
    stats = Stats()
    ratios = WAYBACK_RATIOS if ratios is None else ratios
    start = max(start, WAYBACK_FIRST_DATE)
    end = min(end, WAYBACK_LAST_DATE)
    if start > end:
        return stats
    body = fetch(WAYBACK_URL)
    if body is None:
        raise GoldHistoryError("The Wayback snapshot was not found")
    parsed = parse_wayback(body.decode("utf-8", errors="replace"))
    days = {
        d: derive_gold_purities(rates, ratios) for d, rates in parsed.items() if start <= d <= end
    }
    stats.found_full = set(days)
    for batch_start, batch_end in _month_batches(start, end):
        rows = {d: r for d, r in days.items() if batch_start <= d <= batch_end}
        added = 0
        if dry_run:
            for d in sorted(rows):
                _print_day("wayback", d, rows[d], "")
        elif session is not None:
            added = insert_missing(session, rows)
            stats.inserted += added
        print(f"wayback {batch_start:%Y-%m}: {len(rows)} dates, {added} rows inserted")
    return stats
