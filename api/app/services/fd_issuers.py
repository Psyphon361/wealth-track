"""FD/RD issuer master (fd_issuer_master): banks, NBFCs, HFCs and India Post.

Sources (every one is optional; a failed or missing one is recorded in `errors` and never aborts
the others):
  razorpay    razorpay/ifsc banks.json (code -> {type}) + banknames.json (code -> name); the bank rows
  dicgc       DICGC "list of active insured banks" xlsx, parsed with the standard library only;
              sets dicgc_insured = true on banks whose normalised name matches
  seed_banks  data/fd_issuer_bank_aliases.csv: short names, DICGC name overrides, merged banks
  seed_nbfc   data/fd_issuers_nbfc_hfc.csv: curated NBFCs and HFCs (deposit_status -> accepts_deposits)
  fixed       India Post, always present

Rows are only upserted when something changed, never deleted. If razorpay fails, bank rows are
neither touched nor deactivated; bank rows missing from a successful razorpay run are deactivated
after a grace period (STALE_DAYS), curated NBFC rows as soon as they leave the seed.
"""

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import SequenceMatcher
from io import BytesIO

import sqlalchemy as sa
from fastapi.exceptions import RequestValidationError
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

from app.models.fd_issuer_master import FdIssuerMaster
from app.services import market_files as market

UNKNOWN_ISSUER_MESSAGE = "Select a bank or issuer from the list"

RELEASE_API_URL = "https://api.github.com/repos/razorpay/ifsc/releases/latest"
RELEASE_FALLBACK_URL = "https://github.com/razorpay/ifsc/releases/latest/download/banks.json"
BANKNAMES_URL = "https://raw.githubusercontent.com/razorpay/ifsc/master/src/banknames.json"
DICGC_PAGE_URL = "https://www.dicgc.org.in/insured-banks"
DICGC_FILE_SUFFIX = "list-of-active-insured-banks.xlsx"
SEED_BANKS_FILE = "fd_issuer_bank_aliases.csv"
SEED_NBFC_FILE = "fd_issuers_nbfc_hfc.csv"

# Razorpay bank type -> category
TYPE_CATEGORY = {
    "PSB": "public_sector",
    "Private": "private_sector",
    "SFB": "small_finance",
    "Foreign": "foreign",
    "RRB": "regional_rural",
    "LAB": "local_area",
    "PB": "payments",
    "SCB": "state_coop",
    "DCCB": "district_coop",
    "S-UCB": "urban_coop",
    "O-UCB": "urban_coop",
}
BANK_CATEGORIES = tuple(dict.fromkeys(TYPE_CATEGORY.values()))
# Search order of categories (everything else sorts last)
CATEGORY_PRIORITY = (
    "public_sector", "private_sector", "small_finance", "foreign", "nbfc", "hfc", "post_office",
    "regional_rural", "local_area", "state_coop", "urban_coop", "district_coop",
)  # fmt: skip
# Listed by Razorpay as public-sector banks but not deposit-taking issuers: Reserve Bank of India, General Post Office
NON_ISSUER_CODES = {"RBIN", "GPOX"}
NBFC_CATEGORIES =("nbfc", "hfc")
DEPOSIT_STATUSES = ("permitted", "prior_approval", "not_permitted")
REPORTED_UNMATCHED = ("public_sector", "private_sector", "small_finance")
UNCLAIMED_LIMIT = 30
COLUMNS = [
    "code", "name", "short_name", "category", "regulator", "reg_no", "dicgc_insured",
    "accepts_deposits", "merged_on", "is_active", "sources",
]  # fmt: skip
# Fuzzy DICGC matching: bank category -> the only DICGC sheet it may match against
FUZZY_SHEETS = {
    "urban_coop": "UCBs", "state_coop": "State Co-op Banks", "district_coop": "DCCBs",
    "regional_rural": "RRB",
}  # fmt: skip
FUZZY_GENERIC_WORDS = {
    "BANK", "CO", "COOP", "OPERATIVE", "COOPERATIVE", "SAHAKARI", "NAGARI", "URBAN", "DISTRICT",
    "CENTRAL", "STATE", "LTD", "LIMITED", "THE", "AND",
}  # fmt: skip
FUZZY_MIN_RATIO = 0.92
FUZZY_MIN_MARGIN = 0.05
_MAIN_NS ="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_DROP_WORDS = {"THE", "LTD", "LIMITED"}
_COOP = re.compile(r"\bCO[\s.\-]*OP(?:ERATIVE)?\b")
_DICGC_HREF = re.compile(
    r"""href=["']([^"']*""" + re.escape(DICGC_FILE_SUFFIX) + r""")["']""", re.IGNORECASE
)


@dataclass
class IssuerSources:
    banks_json: bytes | str | None = None
    banknames_json: bytes | str | None = None
    dicgc_xlsx: bytes | None = None
    seed_banks: str | None = None
    seed_nbfc: str | None = None
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class IssuerImportResult:
    total: int
    inserted: int
    updated: int
    unchanged: int
    deactivated: int
    last_seen_refreshed: int
    merge_links_updated: int
    skipped: int
    by_category: dict[str, int]
    by_source: dict[str, int]
    dicgc_names: int
    dicgc_matched: int
    dicgc_unmatched: int  # active bank rows without a DICGC match
    dicgc_unclaimed: int  # DICGC names no bank row claimed
    unmatched_names: dict[str, list[str]]  # unmatched public/private/small finance banks
    unclaimed_names: list[str]
    errors: dict[str, str]
    notes: list[str]
    dicgc_exact: int = 0  # of dicgc_matched, matched by exact name or override (the rest are fuzzy)


@dataclass
class Built:
    rows: list[dict]
    ran: set[str]
    skipped: int = 0
    dicgc_names: int = 0
    dicgc_matched: int = 0
    dicgc_exact: int = 0
    dicgc_unmatched: int = 0
    unmatched_names: dict[str, list[str]] = field(default_factory=dict)
    unclaimed_names: list[str] = field(default_factory=list)
    dicgc_unclaimed: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _row(**values) -> dict:
    row = dict.fromkeys(COLUMNS)
    row.update(accepts_deposits=True, is_active=True, sources=[], merged_into_code=None)
    row.update(values)
    return row


# --- Name normalisation ----------------------------------------------------------


def normalize_name(name: str) -> str:
    """Uppercase, '&' -> AND, unify CO-OP spellings, drop punctuation and THE/LTD/LIMITED."""
    text = name.upper().replace("&", " AND ")
    text = _COOP.sub("COOP", text)
    text = re.sub(r"[^A-Z0-9 ]", " ", text)
    return " ".join(t for t in text.split() if t not in _DROP_WORDS)


# --- Parsers (pure; malformed rows are counted or noted, never raised) ---------------


def parse_razorpay(
    banks_json: bytes | str, banknames_json: bytes | str
) -> tuple[list[dict], dict[str, str], int]:
    """(bank rows, all code -> name, skipped). Types outside TYPE_CATEGORY or without a name are skipped."""
    banks = json.loads(market.text(banks_json))
    names = json.loads(market.text(banknames_json))
    if not isinstance(banks, dict) or not isinstance(names, dict) or not banks:
        raise ValueError("razorpay files have an unexpected shape")
    rows: list[dict] = []
    skipped = 0
    for code, info in banks.items():
        category = TYPE_CATEGORY.get(info.get("type")) if isinstance(info, dict) else None
        name = market.s(names.get(code))
        if category is None or not name or not code.strip():
            skipped += 1
            continue
        rows.append(
            _row(
                code=code.strip()[:40], name=name[:300], category=category, regulator="RBI",
                accepts_deposits=category != "payments" and code not in NON_ISSUER_CODES,
                sources=["razorpay"],
            )  # fmt: skip
        )
    return rows, {k: market.s(v) for k, v in names.items() if isinstance(v, str)}, skipped


def parse_bank_aliases(data: bytes | str) -> list[dict]:
    """code, short_name, merged_into_code, merged_on, dicgc_name (all optional but code)."""
    aliases = []
    for rec in market.records(data):
        code = market.s(rec.get("code"))
        if not code:
            continue
        merged_on = None
        try:
            merged_on = date.fromisoformat(market.s(rec.get("merged_on"))) if market.s(rec.get("merged_on")) else None
        except ValueError:
            merged_on = None
        aliases.append(
            {
                "code": code[:40],
                "short_name": market.opt(rec.get("short_name"), 100),
                "merged_into_code": market.opt(rec.get("merged_into_code"), 40),
                "merged_on": merged_on,
                "dicgc_name": market.opt(rec.get("dicgc_name"), 300),
            }
        )
    return aliases


def parse_nbfc_seed(data: bytes | str) -> tuple[list[dict], int]:
    rows: list[dict] = []
    skipped = 0
    for rec in market.records(data):
        code, name = market.s(rec.get("code")), market.s(rec.get("name"))
        category, status = market.s(rec.get("category")), market.s(rec.get("deposit_status"))
        if not code or not name or category not in NBFC_CATEGORIES or status not in DEPOSIT_STATUSES:
            skipped += 1
            continue
        rows.append(
            _row(
                code=code[:40], name=name[:300], short_name=market.opt(rec.get("short_name"), 100),
                category=category, regulator=market.opt(rec.get("regulator"), 10),
                reg_no=market.opt(rec.get("reg_no"), 40), accepts_deposits=status != "not_permitted",
                sources=["seed_nbfc"],
            )  # fmt: skip
        )
    return rows, skipped


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(_MAIN_NS + "t"))
    value = cell.find(_MAIN_NS + "v")
    if value is None or value.text is None:
        return ""
    if kind == "s":
        index = int(value.text)
        return shared[index] if 0 <= index < len(shared) else ""
    return value.text


def parse_dicgc_xlsx(data: bytes) -> list[tuple[str, str]]:
    """(sheet name, bank name) for every numbered row of every visible sheet.

    Standard library only: sheets come from xl/workbook.xml + its rels, strings from
    xl/sharedStrings.xml. A data row has a number in column A and the bank name in column B.
    """
    with zipfile.ZipFile(BytesIO(data)) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = {
            rel.get("Id"): rel.get("Target", "")
            for rel in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).iter(_MAIN_NS + "si"):
                shared.append("".join(t.text or "" for t in item.iter(_MAIN_NS + "t")))
        found: list[tuple[str, str]] = []
        for sheet in workbook.iter(_MAIN_NS + "sheet"):
            target = rels.get(sheet.get(_REL_ID, ""))
            if sheet.get("state") in ("hidden", "veryHidden") or not target:
                continue
            path = target.lstrip("/") if target.startswith("/") else f"xl/{target}"
            if path not in archive.namelist():
                continue
            for row in ET.fromstring(archive.read(path)).iter(_MAIN_NS + "row"):
                columns: dict[str, str] = {}
                for cell in row.iter(_MAIN_NS + "c"):
                    match = re.match(r"[A-Z]+", cell.get("r", ""))
                    if match:
                        columns[match.group()] = _cell_text(cell, shared).strip()
                number, name = columns.get("A", ""), columns.get("B", "")
                try:
                    float(number)
                except ValueError:
                    continue
                if name:
                    found.append((sheet.get("name", ""), name))
    if not found:
        raise ValueError("DICGC workbook contained no bank rows")
    return found


# --- Build -----------------------------------------------------------------------------


def ifsc_prefix_map(banks_json: bytes | str) -> dict[str, str]:
    """IFSC prefix -> banks.json key, only for prefixes that differ from every key and map to one key.

    banknames.json and the seed use the IFSC prefix; banks.json keys differ for a few banks
    (e.g. prefix ESMF, key ESAF)."""
    banks = json.loads(market.text(banks_json))
    found: dict[str, set[str]] = {}
    for key, info in banks.items():
        ifsc = info.get("ifsc") if isinstance(info, dict) else None
        if isinstance(ifsc, str) and len(ifsc) >= 4 and ifsc[:4] != key and ifsc[:4] not in banks:
            found.setdefault(ifsc[:4].upper(), set()).add(key)
    return {prefix: next(iter(keys)) for prefix, keys in found.items() if len(keys) == 1}


def _apply_aliases(
    bank_rows: dict[str, dict], names: dict[str, str], aliases: list[dict], notes: list[str],
    prefixes: dict[str, str] | None = None,
) -> dict[str, str]:  # fmt: skip
    """Short names, merges and DICGC overrides onto bank rows; adds merged banks Razorpay no longer lists.
    Seed codes may be banks.json keys or IFSC prefixes. Returns code -> normalised DICGC override name."""
    prefixes = prefixes or {}

    def resolve(code: str | None) -> str | None:
        if code is None or code in bank_rows:
            return code
        return prefixes.get(code, code)

    overrides: dict[str, str] = {}
    pending = list(aliases)
    for _ in range(3):  # merged banks may point at other merged banks added in the same pass
        still_pending = []
        for alias in pending:
            raw_code = alias["code"]
            code, target = resolve(raw_code), resolve(alias["merged_into_code"])
            row = bank_rows.get(code)
            if row is None:
                parent = bank_rows.get(target) if target else None
                if parent is None or code not in names:
                    still_pending.append(alias)
                    continue
                row = _row(
                    code=code, name=names[code][:300], category=parent["category"], regulator="RBI",
                    sources=["razorpay"],
                )  # fmt: skip
                bank_rows[code] = row
            if target and target not in bank_rows:
                notes.append(f"alias {code}: merge target {target} unknown, ignored")
                continue
            row["short_name"] = alias["short_name"]
            row["merged_on"] = alias["merged_on"]
            row["merged_into_code"] = target
            row["is_active"] = target is None
            if "seed_banks" not in row["sources"]:
                row["sources"].append("seed_banks")
            if alias["dicgc_name"]:
                overrides[code] = normalize_name(alias["dicgc_name"])
        pending = still_pending
    for alias in pending:
        notes.append(f"alias {alias['code']}: unknown code or merge target, ignored")
    return overrides


def _fuzzy_tokens(key: str) -> str:
    return " ".join(t for t in key.split() if t not in FUZZY_GENERIC_WORDS)


def _fuzzy_match(name: str, candidates: set[str]) -> str | None:
    """The one candidate key whose distinctive tokens are nearly identical to `name`'s, else None."""
    target = _fuzzy_tokens(normalize_name(name))
    if not target:
        return None
    scored = []
    for key in candidates:
        tokens = _fuzzy_tokens(key)
        if tokens:
            scored.append((SequenceMatcher(None, target, tokens).ratio(), key))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < FUZZY_MIN_RATIO:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MIN_MARGIN:
        return None
    return scored[0][1]


def _match_dicgc(
    bank_rows: dict[str, dict], dicgc: list[tuple[str, str]], overrides: dict[str, str], built: Built
) -> None:
    by_norm: dict[str, list[str]] = {}
    sheet_keys: dict[str, set[str]] = {}
    for sheet, name in dicgc:
        key = normalize_name(name)
        by_norm.setdefault(key, []).append(name)
        sheet_keys.setdefault(sheet, set()).add(key)
    claimed: set[str] = set()
    unmatched: list[tuple[str, dict]] = []
    for code, row in bank_rows.items():
        if row["merged_into_code"]:
            continue  # merged banks are not in the active list
        key = overrides.get(code) or normalize_name(row["name"])
        if key in by_norm:
            row["dicgc_insured"] = True
            row["sources"].append("dicgc")
            claimed.add(key)
            built.dicgc_matched += 1
        else:
            unmatched.append((code, row))
    built.dicgc_exact = built.dicgc_matched
    # Conservative fuzzy pass for co-operative banks and RRBs, within the matching DICGC sheet only
    proposals: dict[str, list[dict]] = {}
    for code, row in unmatched:
        sheet = FUZZY_SHEETS.get(row["category"])
        if sheet is None or code in overrides:
            continue
        key = _fuzzy_match(row["name"], sheet_keys.get(sheet, set()) - claimed)
        if key is not None:
            proposals.setdefault(key, []).append(row)
    fuzzy_rows = {id(rows[0]) for rows in proposals.values() if len(rows) == 1}
    for key, rows in proposals.items():
        if len(rows) == 1:  # two banks wanting the same DICGC name: neither is accepted
            rows[0]["dicgc_insured"] = True
            rows[0]["sources"].append("dicgc")
            claimed.add(key)
            built.dicgc_matched += 1
    for code, row in unmatched:
        if id(row) in fuzzy_rows:
            continue
        built.dicgc_unmatched += 1
        if row["category"] in REPORTED_UNMATCHED:
            built.unmatched_names.setdefault(row["category"], []).append(row["name"])
        if code in overrides:
            built.notes.append(f"dicgc_name override for {code} not found in the DICGC list")
    unclaimed = sorted(name for key, names in by_norm.items() if key not in claimed for name in names)
    built.dicgc_unclaimed = len(unclaimed)
    built.unclaimed_names = unclaimed[:UNCLAIMED_LIMIT]
    built.dicgc_names = len(by_norm)


def build_rows(sources: IssuerSources, today: date) -> Built:
    built = Built(rows=[], ran=set(), errors=dict(sources.errors))
    rows: list[dict] = [
        _row(
            code="POST", name="India Post (Department of Posts)", short_name="India Post",
            category="post_office", sources=["fixed"],
        )  # fmt: skip
    ]
    bank_rows: dict[str, dict] = {}

    if sources.banks_json is not None and sources.banknames_json is not None:
        try:
            parsed, names, skipped = parse_razorpay(sources.banks_json, sources.banknames_json)
        except Exception as exc:  # noqa: BLE001 - optional sources must never abort the import
            built.errors["razorpay"] = f"{type(exc).__name__}: {exc}"[:300]
        else:
            built.ran.add("razorpay")
            built.skipped += skipped
            bank_rows = {r["code"]: r for r in parsed}
            overrides: dict[str, str] = {}
            if sources.seed_banks is not None:
                try:
                    aliases = parse_bank_aliases(sources.seed_banks)
                    overrides = _apply_aliases(
                        bank_rows, names, aliases, built.notes, ifsc_prefix_map(sources.banks_json)
                    )
                    built.ran.add("seed_banks")
                except Exception as exc:  # noqa: BLE001
                    built.errors["seed_banks"] = f"{type(exc).__name__}: {exc}"[:300]
            if sources.dicgc_xlsx is not None:
                try:
                    dicgc = parse_dicgc_xlsx(sources.dicgc_xlsx)
                    _match_dicgc(bank_rows, dicgc, overrides, built)
                    built.ran.add("dicgc")
                except Exception as exc:  # noqa: BLE001
                    built.errors["dicgc"] = f"{type(exc).__name__}: {exc}"[:300]
    elif "razorpay" not in built.errors:
        built.errors["razorpay"] = "files not available"
    rows.extend(bank_rows.values())

    if sources.seed_nbfc is not None:
        try:
            nbfc_rows, skipped = parse_nbfc_seed(sources.seed_nbfc)
            taken = {r["code"] for r in rows}
            for row in nbfc_rows:
                if row["code"] in taken:
                    built.skipped += 1
                    built.notes.append(f"nbfc seed code {row['code']} collides with another issuer, ignored")
                    continue
                taken.add(row["code"])
                rows.append(row)
            built.skipped += skipped
            built.ran.add("seed_nbfc")
        except Exception as exc:  # noqa: BLE001
            built.errors["seed_nbfc"] = f"{type(exc).__name__}: {exc}"[:300]

    for row in rows:
        row["last_seen"] = today
        row["sources"] = sorted(set(row["sources"]))
    built.rows = rows
    return built


# --- Fetch -------------------------------------------------------------------------------


def _fetch_banks_json() -> bytes:
    try:
        release = json.loads(
            market.text(market.fetch(RELEASE_API_URL, {"Accept": "application/vnd.github+json"}))
        )
        url = next(
            asset["browser_download_url"]
            for asset in release.get("assets", [])
            if asset.get("name") == "banks.json"
        )
    except Exception:  # noqa: BLE001 - the API is rate limited; the redirect URL needs no API call
        url = RELEASE_FALLBACK_URL
    return market.fetch(url)


def _fetch_dicgc_xlsx() -> bytes:
    page = market.text(market.fetch(DICGC_PAGE_URL))
    match = _DICGC_HREF.search(page)
    if match is None:
        raise LookupError("no active insured banks link on the DICGC page")
    url = urllib.parse.urljoin(DICGC_PAGE_URL, match.group(1))
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path, safe="/%")))
    data = market.fetch(url)
    if market.is_html(data):
        raise LookupError("HTML page instead of the xlsx file")
    return data


def fetch_sources() -> IssuerSources:
    """Download the remote files and read the seed CSVs. Failures are recorded, never raised."""
    sources = IssuerSources()
    try:
        sources.banks_json = _fetch_banks_json()
        sources.banknames_json = market.fetch(BANKNAMES_URL)
    except Exception as exc:  # noqa: BLE001
        sources.banks_json = sources.banknames_json = None
        sources.errors["razorpay"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        sources.dicgc_xlsx = _fetch_dicgc_xlsx()
    except Exception as exc:  # noqa: BLE001
        sources.errors["dicgc"] = f"{type(exc).__name__}: {exc}"[:300]
    for tag, filename in (("seed_banks", SEED_BANKS_FILE), ("seed_nbfc", SEED_NBFC_FILE)):
        try:
            setattr(sources, tag, (market.DATA_DIR / filename).read_text(encoding="utf-8"))
        except OSError as exc:
            sources.errors[tag] = f"{type(exc).__name__}: {filename} not readable"
    return sources


# --- Upsert ------------------------------------------------------------------------------


def _upsert(session: Session, built: Built, today: date) -> tuple[int, int, int, int, int]:
    """Returns (inserted, updated, deactivated, last_seen_refreshed, merge_links_updated). Commits."""
    table = FdIssuerMaster.__table__
    name = table.name
    rows = built.rows
    missing_tags = [t for t in ("razorpay", "dicgc", "seed_banks", "seed_nbfc") if t not in built.ran]
    keep = {"dicgc_insured"}
    if "seed_banks" not in built.ran:
        keep |= {"short_name", "merged_on"}
    data_columns = [c for c in COLUMNS if c != "code"]
    inserted = updated = 0
    for start in range(0, len(rows), market.BATCH_SIZE):
        batch = [{c: row[c] for c in COLUMNS + ["last_seen"]} for row in rows[start:start + market.BATCH_SIZE]]
        statement = pg_insert(FdIssuerMaster).values(batch)
        update = {
            c: sa.func.coalesce(statement.excluded[c], table.c[c]) if c in keep else statement.excluded[c]
            for c in data_columns
        }
        if "seed_banks" not in built.ran:  # a known merge keeps the row inactive while the seed is unavailable
            update["is_active"] = sa.case(
                (table.c.merged_into_id.is_not(None), sa.false()), else_=statement.excluded.is_active
            )
        update["sources"] = sa.literal_column(market.merged_tags_sql(name, missing_tags))
        update["updated_at"] = sa.func.now()
        statement = statement.on_conflict_do_update(
            index_elements=["code"],
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

    last_seen_refreshed = session.execute(
        sa.text(
            f"UPDATE {name} SET last_seen = :today "
            "WHERE code = ANY(:codes) AND (last_seen IS NULL OR last_seen < :cutoff)"
        ).bindparams(
            sa.bindparam("codes", value=[r["code"] for r in rows], type_=ARRAY(sa.String)),
            sa.bindparam("today", value=today, type_=sa.Date),
            sa.bindparam(
                "cutoff", value=today - timedelta(days=market.LAST_SEEN_REFRESH_DAYS), type_=sa.Date
            ),
        )
    ).rowcount

    merge_links = 0
    if {"razorpay", "seed_banks"} <= built.ran:
        bank_rows = [r for r in rows if "razorpay" in r["sources"]]
        merge_links = session.execute(
            sa.text(
                f"UPDATE {name} s SET merged_into_id = t.id, updated_at = now() "
                "FROM unnest(:codes, :targets) AS v(code, target) "
                f"LEFT JOIN {name} t ON t.code = v.target "
                "WHERE s.code = v.code AND s.merged_into_id IS DISTINCT FROM t.id"
            ).bindparams(
                sa.bindparam("codes", value=[r["code"] for r in bank_rows], type_=ARRAY(sa.String)),
                sa.bindparam(
                    "targets", value=[r["merged_into_code"] for r in bank_rows], type_=ARRAY(sa.String)
                ),
            )
        ).rowcount

    deactivated = 0
    cutoff = today - timedelta(days=market.STALE_DAYS)
    for tag, grace in (("razorpay", True), ("seed_nbfc", False)):
        if tag not in built.ran:
            continue
        seen = [r["code"] for r in rows if tag in r["sources"]]
        deactivated += session.execute(
            sa.text(
                f"UPDATE {name} SET is_active = false, updated_at = now() "
                f"WHERE is_active AND :tag = ANY(sources) AND code <> ALL(:codes)"
                + (" AND (last_seen IS NULL OR last_seen < :cutoff)" if grace else "")
            ).bindparams(
                sa.bindparam("tag", value=tag, type_=sa.String),
                sa.bindparam("codes", value=seen, type_=ARRAY(sa.String)),
                *([sa.bindparam("cutoff", value=cutoff, type_=sa.Date)] if grace else []),
            )
        ).rowcount
    session.commit()
    return inserted, updated, deactivated, last_seen_refreshed, merge_links


def import_issuers(session: Session, sources: IssuerSources, today: date) -> IssuerImportResult:
    built = build_rows(sources, today)
    inserted, updated, deactivated, refreshed, merge_links = _upsert(session, built, today)
    by_category: dict[str, int] = {}
    by_source: dict[str, int] = {}
    for row in built.rows:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        for tag in row["sources"]:
            by_source[tag] = by_source.get(tag, 0) + 1
    return IssuerImportResult(
        total=len(built.rows),
        inserted=inserted,
        updated=updated,
        unchanged=len(built.rows) - inserted - updated,
        deactivated=deactivated,
        last_seen_refreshed=refreshed,
        merge_links_updated=merge_links,
        skipped=built.skipped,
        by_category=by_category,
        by_source=by_source,
        dicgc_names=built.dicgc_names,
        dicgc_matched=built.dicgc_matched,
        dicgc_unmatched=built.dicgc_unmatched,
        dicgc_unclaimed=built.dicgc_unclaimed,
        unmatched_names=built.unmatched_names,
        unclaimed_names=built.unclaimed_names,
        errors=built.errors,
        notes=built.notes,
        dicgc_exact=built.dicgc_exact,
    )


# --- Lookup / search -------------------------------------------------------------------


def get_issuer(session: Session, issuer_id: int) -> FdIssuerMaster | None:
    if not 1 <= issuer_id <= 2**31 - 1:
        return None
    return session.get(FdIssuerMaster, issuer_id)


def require_issuer(session: Session, issuer_id: int) -> FdIssuerMaster:
    """Used by FD/RD create/update: unknown id or an issuer that takes no deposits -> 422 on `issuer_id`."""
    issuer = get_issuer(session, issuer_id)
    if issuer is None or not issuer.accepts_deposits:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "issuer_id"),
                    "msg": UNKNOWN_ISSUER_MESSAGE,
                    "input": issuer_id,
                }
            ]
        )
    return issuer


def search_issuers(session: Session, q: str, limit: int = 20) -> list[FdIssuerMaster]:
    """Deposit-taking issuers (merged and inactive ones included, so old holdings stay findable)."""
    if len(q.strip()) < 2:
        return []
    limit = max(1, min(limit, 50))
    statement = sa.select(FdIssuerMaster).where(FdIssuerMaster.accepts_deposits)
    for token in q.split():
        statement = statement.where(
            sa.or_(
                FdIssuerMaster.name.icontains(token, autoescape=True),
                FdIssuerMaster.short_name.icontains(token, autoescape=True),
                FdIssuerMaster.code.icontains(token, autoescape=True),
            )
        )
    priority = sa.case(
        {category: index for index, category in enumerate(CATEGORY_PRIORITY)},
        value=FdIssuerMaster.category,
        else_=len(CATEGORY_PRIORITY),
    )
    statement = statement.order_by(
        priority,
        sa.func.similarity(sa.func.lower(FdIssuerMaster.name), q.strip().lower()).desc(),
        FdIssuerMaster.name,
        FdIssuerMaster.id,
    ).limit(limit)
    return list(session.scalars(statement))
