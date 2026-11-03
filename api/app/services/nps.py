"""NPS scheme master and NAVs from NPS Trust (npstrust.org.in).

Sources (both UTF-8 TSV, dates `YYYY-MM-DD`):
- Latest NAV of every scheme: GET /nav-report-excel
    ID, DATE OF NAV, PFM NAME, SCHEME ID, SCHEME NAME, NAV VALUE
- History of one scheme: GET /scheme-wise-nav-report-excel?navcatdataxls=<PFM code>
    &navyearselxls=all&navsubdataxls=<scheme id>
    ID, DATE OF NAV, PFM ID, PFM NAME, SCHEME ID, SCHEME NAME, NAV VALUE (newest first).
  The response also carries other schemes' rows (e.g. SM001003 returns SM001025 rows from
  2026-04-01), so only rows whose SCHEME ID equals the requested one are kept.

The PFM code is not in the latest file; it is derived from the scheme id: SM<NNN><xxx> -> PFM<NNN>
(verified against the history endpoint for SBI, UTI, LIC, ICICI and HDFC schemes).
"""

import logging
import re
import ssl
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

from app.models.nps import Nps
from app.models.nps_master import NpsMaster, NpsNavHistory, NpsNavHistorySync, NpsNavLatest
from app.schemas.nps import NpsImportResult
from app.services.nav_history import HISTORY_YEARS, _years_ago

LATEST_URL = "https://npstrust.org.in/nav-report-excel"
HISTORY_URL = (
    "https://npstrust.org.in/scheme-wise-nav-report-excel"
    "?navcatdataxls={pfm_code}&navyearselxls=all&navsubdataxls={scheme_id}"
)
FETCH_TIMEOUT = 30
HISTORY_TIMEOUT = 60
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
BATCH_SIZE = 2000
MAX_NAV = Decimal("9999999999")

logger = logging.getLogger(__name__)

_SCHEME_ID = re.compile(r"^SM(\d{3})\d{3}$")
_TIER = re.compile(r"\bTIER\s*-?\s*(II|I)\b", re.IGNORECASE)
_ASSET_CLASS = re.compile(r"\bSCHEME\s+([ECGA])\s*-\s*TIER\b", re.IGNORECASE)


@dataclass(frozen=True)
class SchemeRow:
    scheme_id: str
    pfm_code: str
    pfm_name: str
    scheme_name: str
    tier: str | None
    asset_class: str
    is_active: bool


@dataclass(frozen=True)
class NavRow:
    scheme_id: str
    nav: Decimal
    nav_date: date


@dataclass
class ParseResult:
    rows: list[SchemeRow] = field(default_factory=list)
    navs: list[NavRow] = field(default_factory=list)
    file_date: date | None = None
    skipped: int = 0


# --- Derivation ----------------------------------------------------------------


def derive_pfm_code(scheme_id: str) -> str | None:
    """SM001003 -> PFM001; None when the id does not have the SM<6 digits> shape."""
    match = _SCHEME_ID.match(scheme_id)
    return f"PFM{match.group(1)}" if match else None


def derive_tier(name: str) -> str | None:
    """"I" or "II" from "TIER I", "TIER II", "TIER - II", "TIER- II"; None when the name has no tier."""
    match = _TIER.search(name)
    return match.group(1).upper() if match else None


def derive_asset_class(name: str) -> str:
    """E, C, G or A for the plain "SCHEME <letter> - TIER ..." funds; everything else is "other"
    (central/state govt, NPS Lite, corporate CG, APY, UPS, tax saver, composite and the
    lifecycle/themed funds)."""
    match = _ASSET_CLASS.search(name)
    return match.group(1).upper() if match else "other"


# --- Parsing -------------------------------------------------------------------


def _parse_nav(value: str) -> Decimal | None:
    try:
        nav = Decimal(value.strip()).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None
    return nav if nav.is_finite() and 0 < nav <= MAX_NAV else None


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def parse_latest(text: str) -> ParseResult:
    """Parse the latest-NAV file. Pure; malformed rows are counted in `skipped`, never raised."""
    result = ParseResult()
    seen: set[str] = set()
    for raw in text.lstrip("﻿").splitlines():
        if not raw.strip():
            continue
        fields = [f.strip() for f in raw.split("\t")]
        if len(fields) != 6 or fields[1].upper() == "DATE OF NAV":
            if not (fields and fields[0].upper() == "ID"):
                result.skipped += 1
            continue
        _, date_text, pfm_name, scheme_id, scheme_name, nav_text = fields
        nav_date = _parse_date(date_text)
        nav = _parse_nav(nav_text)
        pfm_code = derive_pfm_code(scheme_id)
        if not scheme_name or not pfm_name or pfm_code is None or scheme_id in seen:
            result.skipped += 1
            continue
        seen.add(scheme_id)
        result.rows.append(
            SchemeRow(
                scheme_id=scheme_id,
                pfm_code=pfm_code,
                pfm_name=pfm_name[:200],
                scheme_name=scheme_name[:300],
                tier=derive_tier(scheme_name),
                asset_class=derive_asset_class(scheme_name),
                is_active=True,
            )
        )
        if nav is not None and nav_date is not None:
            result.navs.append(NavRow(scheme_id=scheme_id, nav=nav, nav_date=nav_date))
    dates = [n.nav_date for n in result.navs]
    result.file_date = max(dates) if dates else None
    return result


def parse_history(text: str, scheme_id: str) -> list[tuple[date, Decimal]]:
    """History file -> [(date, nav)] for `scheme_id` only (the file mixes in other schemes)."""
    rows: dict[date, Decimal] = {}
    for raw in text.lstrip("﻿").splitlines():
        fields = [f.strip() for f in raw.split("\t")]
        if len(fields) != 7 or fields[4] != scheme_id:
            continue
        nav_date = _parse_date(fields[1])
        nav = _parse_nav(fields[6])
        if nav_date is None or nav is None:
            continue
        rows[nav_date] = nav
    return sorted(rows.items())


# --- Fetch ---------------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    # Some system CA stores lack the site's issuer; prefer certifi's bundle when installed.
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _fetch(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:  # noqa: S310
        return response.read().decode("utf-8-sig", errors="replace")


def fetch_latest() -> str:
    return _fetch(LATEST_URL, FETCH_TIMEOUT)


def fetch_history(scheme_id: str) -> list[tuple[date, Decimal]]:
    pfm_code = derive_pfm_code(scheme_id)
    if pfm_code is None:
        return []
    url = HISTORY_URL.format(pfm_code=pfm_code, scheme_id=scheme_id)
    return parse_history(_fetch(url, HISTORY_TIMEOUT), scheme_id)


# --- DB ------------------------------------------------------------------------


def held_scheme_ids(session: Session) -> set[str]:
    """Scheme ids held by any user (nps_holdings)."""
    return set(session.scalars(sa.select(Nps.scheme_id).distinct()))


def _append_today(session: Session, navs: list[NavRow], held: set[str]) -> int:
    values = [
        {"scheme_id": n.scheme_id, "nav_date": n.nav_date, "nav": n.nav}
        for n in navs
        if n.scheme_id in held
    ]
    if not values:
        return 0
    inserted = session.execute(
        pg_insert(NpsNavHistory)
        .values(values)
        .on_conflict_do_nothing(index_elements=["scheme_id", "nav_date"])
        .returning(NpsNavHistory.scheme_id)
    ).all()
    return len(inserted)


def import_latest(session: Session, parsed: ParseResult) -> NpsImportResult:
    """Upsert every scheme and its latest NAV; ids missing from the file become inactive. Never deletes."""
    if not parsed.rows:
        raise ValueError("NPS NAV file contained no scheme rows")

    inserted = updated = 0
    table = NpsMaster.__table__
    columns = [c.name for c in table.columns if c.name != "updated_at"]
    data_columns = [name for name in columns if name != "scheme_id"]
    values = [{name: getattr(row, name) for name in columns} for row in parsed.rows]
    for start in range(0, len(values), BATCH_SIZE):
        statement = pg_insert(NpsMaster).values(values[start:start + BATCH_SIZE])
        update = {name: statement.excluded[name] for name in data_columns}
        update["updated_at"] = sa.func.now()
        statement = statement.on_conflict_do_update(
            index_elements=["scheme_id"],
            set_=update,
            where=sa.tuple_(*[table.c[n] for n in data_columns]).is_distinct_from(
                sa.tuple_(*[statement.excluded[n] for n in data_columns])
            ),
        ).returning(sa.literal_column("(xmax = 0)").label("inserted"))
        for (was_inserted,) in session.execute(statement):
            if was_inserted:
                inserted += 1
            else:
                updated += 1

    deactivated = session.execute(
        sa.text(
            "UPDATE nps_master SET is_active = false, updated_at = now() "
            "WHERE is_active AND scheme_id <> ALL(:ids)"
        ).bindparams(
            sa.bindparam("ids", value=[r.scheme_id for r in parsed.rows], type_=ARRAY(sa.String))
        )
    ).rowcount

    navs_upserted = 0
    nav_table = NpsNavLatest.__table__
    nav_values = [
        {"scheme_id": n.scheme_id, "nav": n.nav, "nav_date": n.nav_date} for n in parsed.navs
    ]
    for start in range(0, len(nav_values), BATCH_SIZE):
        statement = pg_insert(NpsNavLatest).values(nav_values[start:start + BATCH_SIZE])
        statement = statement.on_conflict_do_update(
            index_elements=["scheme_id"],
            set_={
                "nav": statement.excluded.nav,
                "nav_date": statement.excluded.nav_date,
                "updated_at": sa.func.now(),
            },
            where=sa.tuple_(nav_table.c.nav, nav_table.c.nav_date).is_distinct_from(
                sa.tuple_(statement.excluded.nav, statement.excluded.nav_date)
            ),
        ).returning(nav_table.c.scheme_id)
        navs_upserted += len(session.execute(statement).all())

    history_appended = _append_today(session, parsed.navs, held_scheme_ids(session))

    active = session.scalar(sa.select(sa.func.count()).where(NpsMaster.is_active)) or 0
    total = session.scalar(sa.select(sa.func.count()).select_from(NpsMaster)) or 0
    session.commit()
    history_synced = sync_missing_history(session)
    return NpsImportResult(
        rows=len(parsed.rows),
        active=active,
        inactive=total - active,
        file_date=parsed.file_date,
        inserted=inserted,
        updated=updated,
        unchanged=len(parsed.rows) - inserted - updated,
        deactivated=deactivated,
        navs_upserted=navs_upserted,
        history_appended=history_appended,
        history_synced=history_synced,
    )


def store_history(
    session: Session, scheme_id: str, rows: list[tuple[date, Decimal]], today: date, now: datetime
) -> None:
    """Upsert rows within HISTORY_YEARS of today and record the sync. Commits."""
    cutoff = _years_ago(today, HISTORY_YEARS)
    kept = [(d, n) for d, n in rows if cutoff <= d <= today]
    table = NpsNavHistory.__table__
    for start in range(0, len(kept), BATCH_SIZE):
        statement = pg_insert(NpsNavHistory).values(
            [
                {"scheme_id": scheme_id, "nav_date": d, "nav": n}
                for d, n in kept[start:start + BATCH_SIZE]
            ]
        )
        session.execute(
            statement.on_conflict_do_update(
                index_elements=["scheme_id", "nav_date"],
                set_={"nav": statement.excluded.nav},
                where=table.c.nav.is_distinct_from(statement.excluded.nav),
            )
        )
    sync = pg_insert(NpsNavHistorySync).values(scheme_id=scheme_id, synced_at=now)
    session.execute(
        sync.on_conflict_do_update(
            index_elements=["scheme_id"], set_={"synced_at": sync.excluded.synced_at}
        )
    )
    session.commit()


def sync_missing_history(session: Session) -> int:
    """Backfill history for held schemes never synced. Failures are logged, never raised
    (the scheme stays unsynced and the next import retries). Returns the count synced."""
    held = held_scheme_ids(session)
    synced = set(session.scalars(sa.select(NpsNavHistorySync.scheme_id)))
    count = 0
    for scheme_id in sorted(held - synced):
        try:
            rows = fetch_history(scheme_id)
            now = datetime.now(timezone.utc)
            store_history(session, scheme_id, rows, now.date(), now)
            count += 1
        except Exception:  # noqa: BLE001 - history is best effort, never fail the import
            session.rollback()
            logger.warning("NPS history sync failed for scheme %s", scheme_id, exc_info=True)
    return count


def sync_scheme_history(session: Session, scheme_id: str) -> bool:
    """Backfill one scheme's history if it was never synced. Returns True when it ran."""
    if session.get(NpsNavHistorySync, scheme_id) is not None:
        return False
    rows = fetch_history(scheme_id)
    now = datetime.now(timezone.utc)
    store_history(session, scheme_id, rows, now.date(), now)
    return True


def sync_scheme_safely(scheme_id: str) -> None:
    """Background task after a holding is saved: own session, failures logged and swallowed
    (the nightly import retries unsynced held schemes)."""
    from app.db import SessionLocal

    try:
        with SessionLocal() as session:
            try:
                sync_scheme_history(session, scheme_id)
            except Exception:
                session.rollback()
                raise
    except Exception:  # noqa: BLE001 - best effort, never fail the request
        logger.warning("NPS history sync failed for scheme %s", scheme_id, exc_info=True)


# --- Lookups -------------------------------------------------------------------

UNKNOWN_SCHEME_MESSAGE = "Choose a scheme"


def get_scheme(session: Session, scheme_id: str) -> NpsMaster | None:
    if not scheme_id or len(scheme_id) > 20:
        return None
    return session.get(NpsMaster, scheme_id)


def require_scheme(session: Session, scheme_id: str) -> NpsMaster:
    """Used by NPS create/update: unknown scheme -> 422 on `scheme_id`."""
    scheme = get_scheme(session, scheme_id)
    if scheme is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "scheme_id"),
                    "msg": UNKNOWN_SCHEME_MESSAGE,
                    "input": scheme_id,
                }
            ]
        )
    return scheme


def _with_nav(scheme: NpsMaster, nav, nav_date) -> dict:
    return {
        "scheme_id": scheme.scheme_id,
        "scheme_name": scheme.scheme_name,
        "pfm_name": scheme.pfm_name,
        "tier": scheme.tier,
        "asset_class": scheme.asset_class,
        "nav": nav,
        "nav_date": nav_date,
    }


def get_scheme_with_nav(session: Session, scheme_id: str) -> dict | None:
    if not scheme_id or len(scheme_id) > 20:
        return None
    row = session.execute(
        sa.select(NpsMaster, NpsNavLatest.nav, NpsNavLatest.nav_date)
        .outerjoin(NpsNavLatest, NpsNavLatest.scheme_id == NpsMaster.scheme_id)
        .where(NpsMaster.scheme_id == scheme_id)
    ).first()
    return _with_nav(*row) if row else None


def search_schemes(session: Session, q: str, limit: int = 20) -> list[dict]:
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = (
        sa.select(NpsMaster, NpsNavLatest.nav, NpsNavLatest.nav_date)
        .outerjoin(NpsNavLatest, NpsNavLatest.scheme_id == NpsMaster.scheme_id)
        .where(NpsMaster.is_active)
    )
    for token in q.split():
        statement = statement.where(
            sa.or_(
                NpsMaster.scheme_name.icontains(token, autoescape=True),
                NpsMaster.pfm_name.icontains(token, autoescape=True),
            )
        )
    statement = statement.order_by(
        sa.func.similarity(sa.func.lower(NpsMaster.scheme_name), q.strip().lower()).desc(),
        NpsMaster.scheme_name,
        NpsMaster.scheme_id,
    ).limit(limit)
    return [_with_nav(*row) for row in session.execute(statement)]


def previous_navs(session: Session, scheme_ids) -> dict[str, tuple[date, Decimal]]:
    """Per scheme, the stored NAV on the latest date strictly before its latest NAV date.

    One query, DB only. Schemes without such a row are omitted.
    """
    ids = [i for i in scheme_ids if i is not None]
    if not ids:
        return {}
    # Latest date before the scheme's latest NAV date (index seek per scheme), then that row.
    older = sa.orm.aliased(NpsNavHistory)
    prev_date = (
        sa.select(sa.func.max(older.nav_date))
        .where(older.scheme_id == NpsNavLatest.scheme_id, older.nav_date < NpsNavLatest.nav_date)
        .scalar_subquery()
    )
    rows = session.execute(
        sa.select(NpsNavLatest.scheme_id, NpsNavHistory.nav_date, NpsNavHistory.nav)
        .select_from(NpsNavLatest)
        .join(
            NpsNavHistory,
            sa.and_(NpsNavHistory.scheme_id == NpsNavLatest.scheme_id, NpsNavHistory.nav_date == prev_date),
        )
        .where(NpsNavLatest.scheme_id.in_(ids))
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}
