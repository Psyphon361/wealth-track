"""Shared plumbing for the stock and bond masters: downloading NSE/BSE files, CSV and number
parsing, merging by ISIN and the batched "only changed rows" upsert.

The NSE bhavcopy feeds both masters (SME stocks and SGBs), so `fetch_sources` downloads every
file once and each master parses what it needs.
"""

import csv
import io
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
DEBT_URL = "https://nsearchives.nseindia.com/content/equities/DEBT.csv"
NSE_BHAV_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
BSE_BHAV_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{date}_F_0000.CSV"
NSE_SGB_URL = "https://www.nseindia.com/api/sovereign-gold-bonds"
NSE_RATINGS_URL = "https://www.nseindia.com/api/liveBonds-traded-on-cm?type=bonds"
BSE_REFERER = "https://www.bseindia.com/"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SEED_SGB_FILE = "sgb_tranches.csv"
SEED_TAX_FREE_FILE = "tax_free_bonds.csv"
FETCH_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
WALK_BACK_DAYS = 7
STALE_DAYS = 30
BATCH_SIZE = 2000
LAST_SEEN_REFRESH_DAYS = 7

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


@dataclass
class SourceRows:
    rows: list[dict] = field(default_factory=list)
    skipped: int = 0
    excluded: int = 0  # recognised but deliberately left out (e.g. Social Stock Exchange)


@dataclass
class Sources:
    """Raw downloaded files. bhav/bse carry the file date they were found for.

    The bond extras (nse_sgb, nse_ratings JSON, seed CSVs) are optional; a failed or missing one is
    recorded in `extra_errors` under its tag and never aborts the import.
    """

    equity: bytes | str
    etf: bytes | str
    debt: bytes | str
    bhav: tuple[date, bytes] | None = None
    bhav_error: str | None = None
    bse: tuple[date, bytes | str] | None = None
    bse_error: str | None = None
    nse_sgb: bytes | str | None = None
    nse_ratings: bytes | str | None = None
    seed_sgb: str | None = None
    seed_tax_free: str | None = None
    extra_errors: dict[str, str] = field(default_factory=dict)


# --- Parsing helpers -----------------------------------------------------------


def text(data: bytes | str) -> str:
    if isinstance(data, bytes):
        data = data.decode("utf-8-sig", errors="replace")
    return data.lstrip("﻿")


def s(value: str | None) -> str:
    return (value or "").strip()


def opt(value: str | None, limit: int) -> str | None:
    value = s(value)
    return value[:limit] if value else None


def decimal_value(value: str | None, places: str, upper: int) -> Decimal | None:
    try:
        number = Decimal(s(value)).quantize(Decimal(places))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and 0 <= number < upper else None


def face_value(value: str | None) -> Decimal | None:
    return decimal_value(value, "0.01", 10**12)


def parse_date(value: str | None) -> date | None:
    """`25-JUN-2031` (also `25-Jun-31`) -> date."""
    parts = s(value).split("-")
    if len(parts) != 3:
        return None
    try:
        year = int(parts[2])
        if year < 100:
            year += 2000
        return date(year, MONTHS[parts[1].lower()], int(parts[0]))
    except (KeyError, ValueError):
        return None


def records(data: bytes | str):
    """Yield dicts keyed by stripped header names; short rows simply lack the missing keys."""
    reader = csv.reader(io.StringIO(text(data)))
    names = [h.strip() for h in next(reader, [])]
    for values in reader:
        if any(v.strip() for v in values):
            yield dict(zip(names, values, strict=False))


def unzip_first(data: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise ValueError("bhavcopy zip contains no CSV")
        return archive.read(names[0])


def debt_isins(data: bytes | str) -> set[str]:
    """ISINs in NSE DEBT.csv (15th column, no header)."""
    reader = csv.reader(io.StringIO(text(data)))
    next(reader, None)
    found = set()
    for values in reader:
        if len(values) >= 15 and ISIN_RE.match(s(values[14])):
            found.add(s(values[14]))
    return found


# --- Fetch ---------------------------------------------------------------------


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
        return response.read()


def is_html(data: bytes) -> bool:
    return data.lstrip()[:1] == b"<"


def fetch_latest_dated(
    template: str, today: date, headers: dict[str, str] | None = None
) -> tuple[date, bytes]:
    """Walk back from today (up to WALK_BACK_DAYS) to the latest published daily file; 404 = no file."""
    last_error: Exception | None = None
    for offset in range(WALK_BACK_DAYS + 1):
        day = today - timedelta(days=offset)
        try:
            data = fetch(template.format(date=day.strftime("%Y%m%d")), headers)
        except urllib.error.HTTPError as exc:
            if exc.code not in (403, 404):
                raise
            last_error = exc
            continue
        if is_html(data):  # BSE answers a missing file with its HTML shell and status 200
            last_error = LookupError("HTML page instead of a file")
            continue
        return day, data
    raise LookupError(f"no file in the last {WALK_BACK_DAYS + 1} days ({last_error})")


def fetch_sources(today: date) -> Sources:
    """Download every file once. Bhavcopy failures are recorded on the result, never raised."""
    sources = Sources(equity=fetch(EQUITY_URL), etf=fetch(ETF_URL), debt=fetch(DEBT_URL))
    try:
        sources.bhav = fetch_latest_dated(NSE_BHAV_URL, today)
    except Exception as exc:  # noqa: BLE001
        sources.bhav_error = f"{type(exc).__name__}: {exc}"[:300]
    try:
        sources.bse = fetch_latest_dated(BSE_BHAV_URL, today, {"Referer": BSE_REFERER})
    except Exception as exc:  # noqa: BLE001
        sources.bse_error = f"{type(exc).__name__}: {exc}"[:300]
    for tag, url in (("nse_sgb", NSE_SGB_URL), ("nse_ratings", NSE_RATINGS_URL)):
        try:
            data = fetch(url, {"Accept": "application/json"})
            if is_html(data):
                raise LookupError("HTML page instead of JSON")
            setattr(sources, tag, data)
        except Exception as exc:  # noqa: BLE001
            sources.extra_errors[tag] = f"{type(exc).__name__}: {exc}"[:300]
    for tag, filename in (("seed_sgb", SEED_SGB_FILE), ("seed_tax_free", SEED_TAX_FREE_FILE)):
        path = DATA_DIR / filename
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            sources.extra_errors[tag] = f"{type(exc).__name__}: {filename} not readable"
            continue
        setattr(sources, tag, content)
    return sources


# --- Merge ---------------------------------------------------------------------


def merge_by_isin(
    by_source: dict[str, list[dict]],
    seen: dict[str, date],
    order: list[str],
    columns: list[str],
    keep_first: tuple[str, ...],
) -> list[dict]:
    """Merge by ISIN; earlier sources in `order` win. Columns in `keep_first` are never overwritten,
    others are filled when still empty. A row's last_seen is the latest of its sources."""
    merged: dict[str, dict] = {}
    for source in order:
        for row in by_source.get(source, []):
            current = merged.get(row["isin"])
            if current is None:
                merged[row["isin"]] = dict(row, last_seen=seen[source], is_active=True)
                continue
            for column in columns:
                if column not in keep_first and current[column] is None:
                    current[column] = row[column]
            current["last_seen"] = max(current["last_seen"], seen[source])
    return list(merged.values())


def parse_optional(name: str, payload, parser, errors: dict, dates: dict, parsed: dict, seen: dict) -> None:
    """Run an optional source's parser; failure is recorded in `errors`, never raised."""
    if payload is None:
        return
    file_date, data = payload
    try:
        result = parser(data)
        if not result.rows:
            raise ValueError(f"{name} file contained no usable rows")
    except Exception as exc:  # noqa: BLE001 - optional sources must never abort the import
        errors[name] = f"{type(exc).__name__}: {exc}"[:300]
        return
    parsed[name] = result
    seen[name] = file_date
    dates[name] = file_date


# --- Upsert --------------------------------------------------------------------


def is_grace_row(nse_symbol: str | None, nse_series: str | None, grace_series: tuple[str, ...]) -> bool:
    """Rows from daily files that can be missing (NSE bhav series, BSE-only) get a last_seen grace."""
    return nse_symbol is None or (nse_series or "") in grace_series


def merged_tags_sql(table_name: str, missing_tags: list[str]) -> str:
    """SQL for the ON CONFLICT value of a `sources` array: excluded tags + stored tags of missing sources."""
    if not all(re.fullmatch(r"[a-z_]+", tag) for tag in missing_tags):
        raise ValueError("invalid source tag")
    keep = "ARRAY[" + ", ".join(f"'{tag}'" for tag in missing_tags) + "]::varchar[]" if missing_tags else "ARRAY[]::varchar[]"
    return (
        "ARRAY(SELECT DISTINCT t FROM unnest(excluded.sources || ARRAY("
        f"SELECT x FROM unnest({table_name}.sources) x WHERE x = ANY({keep}))) t ORDER BY t)"
    )


@dataclass(frozen=True)
class UpsertStats:
    inserted: int
    updated: int
    deactivated: int
    last_seen_refreshed: int


def upsert_master(
    session: Session,
    model,
    rows: list[dict],
    columns: list[str],
    grace_series: tuple[str, ...],
    today: date,
    keep_columns: tuple[str, ...] = (),
    missing_tags: list[str] | None = None,
) -> UpsertStats:
    """Upsert only changed rows, refresh last_seen weekly for grace rows, deactivate unseen rows
    (grace rows only after STALE_DAYS). Never deletes. Commits.

    `keep_columns` come from optional sources: a NULL in the new row keeps the stored value.
    If `missing_tags` is not None the table has a `sources` array column: the new value is this run's
    tags plus the stored tags of sources that did not run (`missing_tags`), sorted and distinct."""
    table = model.__table__
    name = table.name
    # last_seen is written on insert only; it is refreshed separately (weekly resolution) below.
    data_columns = [c for c in columns if c not in ("isin", "last_seen")]
    inserted = updated = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = [{c: row[c] for c in columns} for row in rows[start:start + BATCH_SIZE]]
        statement = pg_insert(model).values(batch)
        update = {
            c: sa.func.coalesce(statement.excluded[c], table.c[c]) if c in keep_columns else statement.excluded[c]
            for c in data_columns
        }
        if missing_tags is not None:
            update["sources"] = sa.literal_column(merged_tags_sql(name, missing_tags))
        update["updated_at"] = sa.func.now()
        statement = statement.on_conflict_do_update(
            index_elements=["isin"],
            set_=update,
            where=sa.tuple_(*[table.c[c] for c in data_columns]).is_distinct_from(
                sa.tuple_(*[update[c] for c in data_columns])
            ),
        ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
        for (was_inserted,) in session.execute(statement):
            if was_inserted:
                inserted += 1
            else:
                updated += 1

    grace_rows = [r for r in rows if is_grace_row(r["nse_symbol"], r["nse_series"], grace_series)]
    last_seen_refreshed = session.execute(
        sa.text(
            f"UPDATE {name} s SET last_seen = v.seen "
            "FROM unnest(:isins, :seen) AS v(isin, seen) "
            "WHERE s.isin = v.isin AND (s.last_seen IS NULL OR s.last_seen < v.seen - :days)"
        ).bindparams(
            sa.bindparam("isins", value=[r["isin"] for r in grace_rows], type_=ARRAY(sa.String)),
            sa.bindparam("seen", value=[r["last_seen"] for r in grace_rows], type_=ARRAY(sa.Date)),
            sa.bindparam("days", value=LAST_SEEN_REFRESH_DAYS, type_=sa.Integer),
        )
    ).rowcount

    # Rows from the always-required lists (NSE symbol, non-grace series) deactivate immediately;
    # grace rows (bhav series, BSE-only) only once last_seen is older than STALE_DAYS.
    deactivated = session.execute(
        sa.text(
            f"UPDATE {name} SET is_active = false, updated_at = now() "
            "WHERE is_active AND isin <> ALL(:isins) AND ("
            "(nse_symbol IS NOT NULL AND COALESCE(nse_series, '') <> ALL(:grace_series)) "
            "OR last_seen IS NULL OR last_seen < :cutoff)"
        ).bindparams(
            sa.bindparam("isins", value=[r["isin"] for r in rows], type_=ARRAY(sa.String)),
            sa.bindparam("grace_series", value=list(grace_series), type_=ARRAY(sa.String)),
            sa.bindparam("cutoff", value=today - timedelta(days=STALE_DAYS), type_=sa.Date),
        )
    ).rowcount
    session.commit()
    return UpsertStats(inserted, updated, deactivated, last_seen_refreshed)
