"""Historical NAV lookup for mutual fund schemes, backed by mfapi.in and cached in Postgres."""

import json
import logging
import urllib.error
import urllib.request
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.mf_master import MFNavHistory, MFNavHistorySync, MFNavLatest

MFAPI_URL = "https://api.mfapi.in/mf/{scheme_code}"
FETCH_TIMEOUT = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HISTORY_YEARS = 10
REFRESH_AFTER = timedelta(hours=24)
BATCH_SIZE = 2000
MAX_NAV = Decimal("9999999999")
FUTURE_DATE_MESSAGE = "Date cannot be in the future"

logger = logging.getLogger(__name__)

NavRow = tuple[date, Decimal]


class NavSourceError(Exception):
    """mfapi.in could not be reached or answered with a server error."""


# --- Pure helpers --------------------------------------------------------------


def parse_mfapi(payload) -> list[NavRow]:
    """mfapi.in JSON -> [(date, nav)]; rows with a bad date or a non-positive NAV are skipped."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    rows: list[NavRow] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            day, month, year = str(item.get("date", "")).strip().split("-")
            nav_date = date(int(year), int(month), int(day))
            nav = Decimal(str(item.get("nav", "")).strip()).quantize(Decimal("0.0001"))
        except (ValueError, InvalidOperation):
            continue
        if not nav.is_finite() or not 0 < nav <= MAX_NAV:
            continue
        rows.append((nav_date, nav))
    return rows


def pick_on_or_before(rows: list[NavRow], on_date: date) -> NavRow | None:
    """The row with the greatest date <= on_date, or None. Input order does not matter."""
    ordered = sorted(rows, key=lambda r: r[0])
    index = bisect_right([r[0] for r in ordered], on_date)
    return ordered[index - 1] if index else None


def pick_before(rows: list[NavRow], before_date: date) -> NavRow | None:
    """The row with the greatest date strictly before before_date, or None."""
    earlier = [r for r in rows if r[0] < before_date]
    return max(earlier, key=lambda r: r[0]) if earlier else None


def validate_not_future(on_date: date, today: date | None = None) -> None:
    if on_date > (today or date.today()):
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("query", "date"),
                    "msg": FUTURE_DATE_MESSAGE,
                    "input": on_date.isoformat(),
                }
            ]
        )


def _years_ago(today: date, years: int) -> date:
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 Feb
        return today.replace(year=today.year - years, day=28)


# --- Source --------------------------------------------------------------------


def fetch_mfapi(scheme_code: int) -> list[NavRow]:
    """Download the full NAV history. Unknown code -> []. Network/5xx/garbage -> NavSourceError."""
    request = urllib.request.Request(
        MFAPI_URL.format(scheme_code=scheme_code),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return []
        raise NavSourceError(f"mfapi.in returned {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise NavSourceError(str(exc)) from exc
    return parse_mfapi(payload)


# --- DB ------------------------------------------------------------------------


def _history_on_or_before(session: Session, scheme_code: int, on_date: date) -> NavRow | None:
    row = session.execute(
        sa.select(MFNavHistory.nav_date, MFNavHistory.nav)
        .where(MFNavHistory.scheme_code == scheme_code, MFNavHistory.nav_date <= on_date)
        .order_by(MFNavHistory.nav_date.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def previous_navs(session: Session, scheme_codes) -> dict[int, NavRow]:
    """Per scheme, the stored NAV on the latest date strictly before its latest NAV date.

    One query, DB only (no network). Schemes without such a row are omitted.
    """
    codes = [c for c in scheme_codes if c is not None]
    if not codes:
        return {}
    ranked = (
        sa.select(
            MFNavHistory.scheme_code.label("scheme_code"),
            MFNavHistory.nav_date.label("nav_date"),
            MFNavHistory.nav.label("nav"),
            sa.func.row_number()
            .over(
                partition_by=MFNavHistory.scheme_code,
                order_by=MFNavHistory.nav_date.desc(),
            )
            .label("rn"),
        )
        .join(MFNavLatest, MFNavLatest.scheme_code == MFNavHistory.scheme_code)
        .where(
            MFNavHistory.scheme_code.in_(codes),
            MFNavHistory.nav_date < MFNavLatest.nav_date,
        )
        .subquery()
    )
    rows = session.execute(
        sa.select(ranked.c.scheme_code, ranked.c.nav_date, ranked.c.nav).where(ranked.c.rn == 1)
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def store_history(
    session: Session, scheme_code: int, rows: list[NavRow], today: date, now: datetime
) -> None:
    """Upsert rows within HISTORY_YEARS of today and record the sync. Commits."""
    cutoff = _years_ago(today, HISTORY_YEARS)
    kept = [(d, n) for d, n in rows if cutoff <= d <= today]
    table = MFNavHistory.__table__
    for start in range(0, len(kept), BATCH_SIZE):
        statement = pg_insert(MFNavHistory).values(
            [
                {"scheme_code": scheme_code, "nav_date": d, "nav": n}
                for d, n in kept[start:start + BATCH_SIZE]
            ]
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["scheme_code", "nav_date"],
                set_={"nav": statement.excluded.nav},
                where=table.c.nav.is_distinct_from(statement.excluded.nav),
            )
        )
    first = min((d for d, _ in kept), default=None)
    last = max((d for d, _ in kept), default=None)
    sync = pg_insert(MFNavHistorySync).values(
        scheme_code=scheme_code, first_date=first, last_date=last, fetched_at=now
    )
    session.execute(
        sync.on_conflict_do_update(
            index_elements=["scheme_code"],
            set_={
                "first_date": sync.excluded.first_date,
                "last_date": sync.excluded.last_date,
                "fetched_at": sync.excluded.fetched_at,
            },
        )
    )
    session.commit()


def schemes_needing_history(held, synced) -> list[int]:
    """Held scheme codes with no history sync record yet, sorted. Pure (no DB, no network)."""
    done = set(synced)
    return sorted({c for c in held if c is not None and c not in done})


def sync_missing_history(session: Session) -> int:
    """Fetch history (mfapi.in) for held schemes never synced. Failures are logged, never raised.

    Schemes whose fetch fails stay unsynced and are retried by the next import; a successful
    fetch records a sync row, so the 24 h refetch limit applies afterwards. Returns the count synced.
    """
    held = session.scalars(
        sa.text("SELECT DISTINCT scheme_code FROM mutual_funds WHERE scheme_code IS NOT NULL")
    ).all()
    synced = session.scalars(sa.select(MFNavHistorySync.scheme_code)).all()
    count = 0
    for code in schemes_needing_history(held, synced):
        try:
            rows = fetch_mfapi(code)
            now = datetime.now(timezone.utc)
            store_history(session, code, rows, now.date(), now)
            count += 1
        except Exception:  # noqa: BLE001 - history is best effort, never fail the import
            session.rollback()
            logger.warning("NAV history sync failed for scheme %s", code, exc_info=True)
    return count


def resolve_nav(session: Session, scheme_code: int, on_date: date) -> dict | None:
    """NAV on or before `on_date` as {nav_date, nav, source}, or None when not published.

    Raises NavSourceError when mfapi.in is needed but unavailable.
    """
    latest = session.get(MFNavLatest, scheme_code)
    if latest is not None and on_date >= latest.nav_date:
        return {"nav_date": latest.nav_date, "nav": latest.nav, "source": "latest"}

    sync = session.get(MFNavHistorySync, scheme_code)

    def from_history() -> dict | None:
        if sync is None or sync.first_date is None or sync.first_date > on_date:
            return None
        found = _history_on_or_before(session, scheme_code, on_date)
        return {"nav_date": found[0], "nav": found[1], "source": "history"} if found else None

    result = from_history()
    if result is not None:
        return result

    now = datetime.now(timezone.utc)
    if sync is not None and now - sync.fetched_at <= REFRESH_AFTER:
        return None
    rows = fetch_mfapi(scheme_code)
    store_history(session, scheme_code, rows, now.date(), now)
    sync = session.get(MFNavHistorySync, scheme_code)
    session.refresh(sync)
    return from_history()


def append_today_for_holdings(session: Session, navs: list[tuple[int, date, Decimal]]) -> int:
    """Daily import hook: store the latest NAV in history for schemes held in mutual_funds.

    `navs` is [(scheme_code, nav_date, nav)]. Returns the number of history rows inserted.
    Does not commit.
    """
    held = set(
        session.scalars(
            sa.text("SELECT DISTINCT scheme_code FROM mutual_funds WHERE scheme_code IS NOT NULL")
        )
    )
    values = [
        {"scheme_code": code, "nav_date": d, "nav": n} for code, d, n in navs if code in held
    ]
    if not values:
        return 0
    inserted = session.execute(
        pg_insert(MFNavHistory)
        .values(values)
        .on_conflict_do_nothing(index_elements=["scheme_code", "nav_date"])
        .returning(MFNavHistory.scheme_code)
    ).all()
    for code, d, _ in navs:
        if code in held:
            session.execute(
                sa.update(MFNavHistorySync)
                .where(
                    MFNavHistorySync.scheme_code == code,
                    sa.or_(MFNavHistorySync.last_date.is_(None), MFNavHistorySync.last_date < d),
                )
                .values(last_date=d)
            )
    return len(inserted)
