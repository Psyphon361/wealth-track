"""AMFI scheme master: parse NAVAll.txt, import it, and search it.

NAVAll.txt format (`;` separated, `-` means none, dates `DD-Mon-YYYY`):
    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date
Lines without `;` are headers: a category header such as
`Open Ended Schemes(Debt Scheme - Liquid Fund)`, or otherwise an AMC header.
"""

import re
import urllib.request
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

from app.models.mf_scheme import MFNavLatest, MFScheme

NAVALL_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
FETCH_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
STALE_DAYS = 30
BATCH_SIZE = 2000
MAX_NAV = Decimal("9999999999")
MAX_SCHEME_CODE = 2_147_483_647
UNKNOWN_SCHEME_MESSAGE = "Select a scheme from the list"

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_CATEGORY_HEADER = re.compile(
    r"^(Open Ended|Close Ended|Interval Fund) Schemes?\s*\((.*)\)\s*$", re.IGNORECASE
)
_PREFIXES = {"open ended": "", "close ended": "Close Ended - ", "interval fund": "Interval - "}


@dataclass(frozen=True)
class SchemeRow:
    scheme_code: int
    name: str
    amc: str | None
    amfi_category: str | None
    category: str
    plan: str | None
    option: str | None
    idcw_frequency: str | None
    isin_growth_payout: str | None
    isin_reinvest: str | None
    is_active: bool


@dataclass(frozen=True)
class NavRow:
    scheme_code: int
    nav: Decimal
    nav_date: date


@dataclass
class ParseResult:
    rows: list[SchemeRow] = field(default_factory=list)  # static master data
    navs: list[NavRow] = field(default_factory=list)  # latest NAV, only rows with a valid NAV + date
    file_date: date | None = None
    skipped: int = 0


@dataclass(frozen=True)
class ImportResult:
    rows: int
    active: int
    inactive: int
    file_date: date | None
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    navs_upserted: int


# --- Normalisation -------------------------------------------------------------


def map_category(amfi_category: str | None) -> str:
    """AMFI category text -> app category enum."""
    if not amfi_category:
        return "other"
    text = amfi_category
    for prefix in _PREFIXES.values():
        if prefix and text.startswith(prefix):
            text = text[len(prefix):]
    t = text.lower()
    if re.search(r"\belss\b", t):
        return "elss"
    if t.startswith("equity scheme"):
        return "equity"
    if t.startswith(("debt scheme", "income/debt oriented")):
        if any(word in t for word in ("liquid", "overnight", "money market")):
            return "liquid"
        return "debt"
    if t.startswith("hybrid scheme"):
        return "hybrid"
    if "index fund" in t or "other etf" in t:
        return "index"
    return "other"


_IDCW = re.compile(r"idcw|dividend|income distribution")
_FREQUENCIES = [
    ("half_yearly", re.compile(r"half[\s-]*yearly")),
    ("daily", re.compile(r"\bdaily\b")),
    ("weekly", re.compile(r"\bweekly\b")),
    ("monthly", re.compile(r"\bmonthly\b")),
    ("quarterly", re.compile(r"\bquarterly\b")),
    ("annual", re.compile(r"\b(annual|yearly)\b")),
]
_NAME_GROWTH = re.compile(r"(?:^|[\s\-(/])growth(?:\s+(?:option|plan))?\s*\)?\s*$")
_NAME_BONUS = re.compile(r"(?:^|[\s\-(/])bonus(?:\s+(?:option|plan))?\s*\)?\s*$")


def idcw_frequency(text: str) -> str | None:
    t = text.lower()
    for name, pattern in _FREQUENCIES:
        if pattern.search(t):
            return name
    return None


def normalise_option(text: str) -> tuple[str, str | None]:
    """Option column text -> (growth|idcw|bonus|other, idcw frequency)."""
    t = text.lower()
    if _IDCW.search(t):
        return "idcw", idcw_frequency(t)
    if "bonus" in t:
        return "bonus", None
    if "growth" in t or "cumulative" in t:
        return "growth", None
    return "other", None


def infer_option_from_name(name: str) -> tuple[str | None, str | None]:
    t = name.lower()
    if _IDCW.search(t):
        return "idcw", idcw_frequency(t)
    if _NAME_BONUS.search(t):
        return "bonus", None
    if _NAME_GROWTH.search(t):
        return "growth", None
    return None, None


def normalise_plan(text: str, name: str) -> str | None:
    for source in (text.lower(), name.lower()):
        if re.search(r"\bdirect\b", source):
            return "direct"
        if re.search(r"\bregular\b", source):
            return "regular"
    return None


# --- Parsing -------------------------------------------------------------------


def _clean(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "-") else value


def _parse_date(value: str) -> date | None:
    parts = value.strip().split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[2]), _MONTHS[parts[1].lower()], int(parts[0]))
    except (KeyError, ValueError):
        return None


def _parse_nav(value: str) -> Decimal | None:
    try:
        nav = Decimal(value.strip()).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError):
        return None
    return nav if nav.is_finite() and 0 <= nav <= MAX_NAV else None


def parse_navall(text: str) -> ParseResult:
    """Parse NAVAll.txt. Pure; malformed lines are counted in `skipped`, never raised."""
    parsed: dict[int, tuple] = {}
    result = ParseResult()
    category: str | None = None
    amc: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            match = _CATEGORY_HEADER.match(line)
            if match:
                kind = match.group(1).lower()
                category = f"{_PREFIXES[kind]}{match.group(2).strip()}"
            else:
                amc = line
            continue
        fields = line.split(";")
        if len(fields) != 8 or not fields[0].strip().isdigit():
            if not line.lower().startswith("scheme code"):
                result.skipped += 1
            continue
        code = int(fields[0])
        name = fields[3].strip()
        if not name or code > MAX_SCHEME_CODE:
            result.skipped += 1
            continue
        if code in parsed:
            result.skipped += 1
        parsed[code] = (
            code, name, amc, category, fields[1], fields[2], fields[4], fields[5],
            _parse_nav(fields[6]), _parse_date(fields[7]),
        )  # fmt: skip

    dates = [item[9] for item in parsed.values() if item[9] is not None]
    result.file_date = max(dates) if dates else None
    cutoff = result.file_date - timedelta(days=STALE_DAYS) if result.file_date else None

    for code, name, amc_, cat, isin1, isin2, plan, option, nav, nav_date in parsed.values():
        plan_value = normalise_plan(plan, name)
        option_text = option.strip()
        if option_text:
            option_value, frequency = normalise_option(option_text)
        else:
            option_value, frequency = infer_option_from_name(name)
        result.rows.append(
            SchemeRow(
                scheme_code=code,
                name=name[:300],
                amc=amc_[:200] if amc_ else None,
                amfi_category=cat[:200] if cat else None,
                category=map_category(cat),
                plan=plan_value,
                option=option_value,
                idcw_frequency=frequency,
                isin_growth_payout=_clean(isin1),
                isin_reinvest=_clean(isin2),
                is_active=bool(nav_date and cutoff and nav_date >= cutoff),
            )
        )
        if nav is not None and nav_date is not None:
            result.navs.append(NavRow(scheme_code=code, nav=nav, nav_date=nav_date))
    return result


# --- Fetch / import ------------------------------------------------------------


def fetch_navall() -> str:
    request = urllib.request.Request(NAVALL_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def import_navall(session: Session, text: str) -> ImportResult:
    """Upsert every scheme in the file; codes missing from the file become inactive. Never deletes."""
    parsed = parse_navall(text)
    if not parsed.rows:
        raise ValueError("NAVAll file contained no scheme rows")

    inserted = updated = 0
    columns = [c.name for c in MFScheme.__table__.columns if c.name != "updated_at"]
    data_columns = [name for name in columns if name != "scheme_code"]
    table = MFScheme.__table__
    values = [{name: getattr(row, name) for name in columns} for row in parsed.rows]
    for start in range(0, len(values), BATCH_SIZE):
        statement = pg_insert(MFScheme).values(values[start:start + BATCH_SIZE])
        update = {name: statement.excluded[name] for name in data_columns}
        update["updated_at"] = sa.func.now()
        statement = statement.on_conflict_do_update(
            index_elements=["scheme_code"],
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
            "UPDATE mf_schemes SET is_active = false, updated_at = now() "
            "WHERE is_active AND scheme_code <> ALL(:codes)"
        ).bindparams(
            sa.bindparam(
                "codes", value=[r.scheme_code for r in parsed.rows], type_=ARRAY(sa.Integer)
            )
        )
    ).rowcount

    navs_upserted = 0
    nav_table = MFNavLatest.__table__
    nav_values = [
        {"scheme_code": n.scheme_code, "nav": n.nav, "nav_date": n.nav_date} for n in parsed.navs
    ]
    for start in range(0, len(nav_values), BATCH_SIZE):
        statement = pg_insert(MFNavLatest).values(nav_values[start:start + BATCH_SIZE])
        statement = statement.on_conflict_do_update(
            index_elements=["scheme_code"],
            set_={
                "nav": statement.excluded.nav,
                "nav_date": statement.excluded.nav_date,
                "updated_at": sa.func.now(),
            },
            where=sa.tuple_(nav_table.c.nav, nav_table.c.nav_date).is_distinct_from(
                sa.tuple_(statement.excluded.nav, statement.excluded.nav_date)
            ),
        ).returning(nav_table.c.scheme_code)
        navs_upserted += len(session.execute(statement).all())

    active = session.scalar(sa.select(sa.func.count()).where(MFScheme.is_active)) or 0
    total = session.scalar(sa.select(sa.func.count()).select_from(MFScheme)) or 0
    session.commit()
    return ImportResult(
        rows=len(parsed.rows),
        active=active,
        inactive=total - active,
        file_date=parsed.file_date,
        inserted=inserted,
        updated=updated,
        unchanged=len(parsed.rows) - inserted - updated,
        deactivated=deactivated,
        navs_upserted=navs_upserted,
    )


# --- Lookup / search -----------------------------------------------------------


def get_scheme(session: Session, scheme_code: int) -> MFScheme | None:
    if not 1 <= scheme_code <= MAX_SCHEME_CODE:
        return None
    return session.get(MFScheme, scheme_code)


def require_scheme(session: Session, scheme_code: int) -> MFScheme:
    """Used by MF create/update: unknown code -> 422 on `scheme_code`."""
    scheme = get_scheme(session, scheme_code)
    if scheme is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "scheme_code"),
                    "msg": UNKNOWN_SCHEME_MESSAGE,
                    "input": scheme_code,
                }
            ]
        )
    return scheme


def _with_nav(scheme: MFScheme, nav, nav_date) -> dict:
    data = {c.name: getattr(scheme, c.name) for c in MFScheme.__table__.columns}
    return {**data, "nav": nav, "nav_date": nav_date}


def get_scheme_with_nav(session: Session, scheme_code: int) -> dict | None:
    if not 1 <= scheme_code <= MAX_SCHEME_CODE:
        return None
    row = session.execute(
        sa.select(MFScheme, MFNavLatest.nav, MFNavLatest.nav_date)
        .outerjoin(MFNavLatest, MFNavLatest.scheme_code == MFScheme.scheme_code)
        .where(MFScheme.scheme_code == scheme_code)
    ).first()
    return _with_nav(*row) if row else None


def search_schemes(session: Session, q: str, limit: int = 20) -> list[dict]:
    tokens = q.split()
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = (
        sa.select(MFScheme, MFNavLatest.nav, MFNavLatest.nav_date)
        .outerjoin(MFNavLatest, MFNavLatest.scheme_code == MFScheme.scheme_code)
        .where(MFScheme.is_active)
    )
    for token in tokens:
        statement = statement.where(
            sa.or_(
                MFScheme.name.icontains(token, autoescape=True),
                MFScheme.amc.icontains(token, autoescape=True),
                MFScheme.plan.icontains(token, autoescape=True),
                MFScheme.option.icontains(token, autoescape=True),
            )
        )
    statement = statement.order_by(
        sa.func.similarity(sa.func.lower(MFScheme.name), q.strip().lower()).desc(),
        MFScheme.name,
        MFScheme.scheme_code,
    ).limit(limit)
    return [_with_nav(*row) for row in session.execute(statement)]
