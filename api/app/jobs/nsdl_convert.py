"""Convert the NSDL India Bond Info "List of Securities" xlsx export into api/data/nsdl_securities.csv.

Local tool (needs openpyxl, a dev dependency): `python -m app.jobs.nsdl_convert <xlsx> [--as-of YYYY-MM-DD]`.
The generated CSV is committed and read by the bond import (source tag `nsdl`); prod never reads the xlsx.
"""

import argparse
import csv
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from app.services import market_files as market

OUTPUT = market.DATA_DIR / market.NSDL_FILE
COLUMNS = [
    "isin", "issuer", "instrument_type", "issue_mode", "tax_category", "face_value", "issue_size",
    "allotment_date", "maturity_date", "is_perpetual", "coupon_rate", "coupon_type", "interest_frequency",
    "rating", "rating_agency", "issuer_ownership", "status", "as_of",
]  # fmt: skip
# Source column headers (xlsx row 1).
HEADERS = {
    "isin": "ISIN", "issuer": "Name of Issuer", "instrument_type": "Type of Instrument",
    "issue_mode": "Mode of Issue", "tax_category": "Category of Issue", "face_value": "Face Value(in Rs.)",
    "issue_size": "Issue Size(in Rs.)", "allotment": "Date of Allotment",
    "redemption": "Date of Redemption/Conversion", "coupon": "Coupon Rate (%)", "coupon_type": "Coupon Type",
    "frequency": "Frequency of Interest Payment", "rating": "Credit Rating",
    "ownership": "Type of Issuer-Ownership", "status": "Instrument Status",
}  # fmt: skip
PERPETUAL_DATE = "31-12-9999"
ACRONYMS = {
    "REC", "PFC", "NHAI", "IRFC", "NTPC", "HUDCO", "IIFCL", "NABARD", "SIDBI", "NHB", "LIC", "HDFC", "ICICI",
    "SBI", "IDFC", "IDBI", "ONGC", "GAIL", "BPCL", "HPCL", "IOC", "NHPC", "SJVN", "IREDA", "PSU", "IFCI",
    "EXIM", "NLC", "SAIL", "NMDC", "MMRDA", "UCO", "IIFL", "LLP", "NBFC", "HSBC", "BMW", "TVS", "JSW", "JM",
}  # fmt: skip
NOT_ACRONYMS = {"LTD", "PVT", "CO", "MFG", "BY", "THE", "MRS", "MR", "DR"}  # vowel-less words that stay title-cased
_VOWELS = set("AEIOU")
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_AGENCY_ALIASES = {"IVR": "INFOMERICS", "INFOMERICS": "INFOMERICS"}
_RATING_NOISE = re.compile(r"\([^)]*\)")
_NO_RATING = re.compile(r"^(WD|WITHDRAWN)\b", re.IGNORECASE)
_SKIPPED_PREFIXES = {"PROVISIONAL"}

INSTRUMENT_TYPES = {"debentures": "debentures", "bonds": "bonds"}
ISSUE_MODES = {
    "public issue": "public", "private placement": "private", "private placement (ebp)": "private",
    "private placement (non-ebp)": "private", "rights issue": "rights", "bonus": "bonus",
    "others": "other", "scheme of arrangement": "other",
}  # fmt: skip
TAX_CATEGORIES = {"taxable": "taxable", "taxfree": "taxfree"}
COUPON_TYPES = {"simple": "simple", "compounding": "compounding"}
FREQUENCIES = {
    "twelve times a year": "monthly", "quarterly": "quarterly", "four times a year": "quarterly",
    "twice a year": "half_yearly", "once a year": "yearly", "on maturity": "on_maturity",
    "on maturity/put-call": "on_maturity", "no occurence": "none", "irregular occurence": "irregular",
    "at any time": "irregular", "thrice a year": "irregular", "every 3 years": "irregular",
    "every 5 years": "irregular", "every 10 years": "irregular",
}  # fmt: skip
OWNERSHIPS = {
    "non psu": "non_psu", "public sector undertaking (psu)": "psu", "psu": "psu",
    "issuer under ildm regulations": "ildm", "ildm": "ildm",
}  # fmt: skip
STATUSES = {"active": "active", "suspended": "suspended"}


def clean(value) -> str:
    """Any cell value -> trimmed single-spaced string ('' for None)."""
    return " ".join(str(value).split()) if value is not None else ""


def normalise_date(value) -> str:
    """'DD-MM-YYYY' -> 'YYYY-MM-DD'; '' when blank or invalid."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return datetime.strptime(clean(value), "%d-%m-%Y").date().isoformat()
    except ValueError:
        return ""


def is_perpetual(value) -> bool:
    return clean(value) == PERPETUAL_DATE


def number(value, upper: int) -> str:
    """Plain decimal text without trailing zeros; '' if not a number in [0, upper)."""
    try:
        parsed = Decimal(clean(value))
    except InvalidOperation:
        return ""
    if not parsed.is_finite() or not 0 <= parsed < upper:
        return ""
    return f"{parsed.normalize():f}" if parsed else "0"


def normalise_frequency(value) -> str:
    return FREQUENCIES.get(clean(value).lower(), "")


def normalise_coupon(value, frequency: str = "") -> str:
    """'7.79' / '9.05%' -> number; non-numeric text -> ''. A 0 is kept only for zero-coupon paper
    (interest on maturity or no frequency); 0 with a periodic frequency is unknown -> ''."""
    text = clean(value)
    if text.endswith("%"):
        text = text[:-1].strip()
    result = number(text, 1000)
    if result == "0" and frequency not in ("", "on_maturity"):
        return ""
    return result


def _issuer_word(match: re.Match) -> str:
    word = match.group(0)
    upper = word.upper()
    if len(word) == 1 or upper in ACRONYMS:
        return upper
    if len(word) <= 4 and upper not in NOT_ACRONYMS and not (set(upper) & _VOWELS):
        return upper
    return word[0].upper() + word[1:].lower()


def title_issuer(value) -> str:
    """'RELIANCE INDUSTRIES LIMITED' -> 'Reliance Industries Limited'; keeps acronyms (HDFC, NTPC, L&T)."""
    return _WORD.sub(_issuer_word, clean(value))


def normalise_choice(value, mapping: dict[str, str]) -> str:
    return mapping.get(clean(value).lower(), "")


def normalise_status(value) -> str:
    return STATUSES.get(clean(value).lower(), "active")


def split_ratings(value) -> tuple[str, str]:
    """'CRISIL AAA/Stable ();CARE AAA/Stable ()' -> ('AAA/Stable', 'CRISIL, CARE'). Annotations in
    parentheses ('()', '(ISSUER NOT COOPERATING*)') are dropped, as are withdrawn (WD) ratings; both
    results are distinct, in first-seen order."""
    ratings: list[str] = []
    agencies: list[str] = []
    for part in clean(value).split(";"):
        tokens = clean(_RATING_NOISE.sub(" ", part)).split(" ")
        while tokens and tokens[0].upper() in _SKIPPED_PREFIXES:
            tokens = tokens[1:]
        if len(tokens) < 2:
            continue
        agency, rating = tokens[0].upper(), " ".join(tokens[1:])
        if _NO_RATING.match(rating):
            continue
        agency = _AGENCY_ALIASES.get(agency, agency)
        if rating not in ratings:
            ratings.append(rating)
        if agency not in agencies:
            agencies.append(agency)
    return ", ".join(ratings), ", ".join(agencies)


def convert_row(record: dict, as_of: str) -> dict | None:
    """One xlsx row (header -> cell) -> output record, or None when the ISIN is invalid."""
    isin = clean(record.get(HEADERS["isin"])).upper()
    if not market.ISIN_RE.match(isin):
        return None
    frequency = normalise_frequency(record.get(HEADERS["frequency"]))
    rating, agency = split_ratings(record.get(HEADERS["rating"]))
    perpetual = is_perpetual(record.get(HEADERS["redemption"]))
    return {
        "isin": isin,
        "issuer": title_issuer(record.get(HEADERS["issuer"])),
        "instrument_type": normalise_choice(record.get(HEADERS["instrument_type"]), INSTRUMENT_TYPES),
        "issue_mode": normalise_choice(record.get(HEADERS["issue_mode"]), ISSUE_MODES),
        "tax_category": normalise_choice(record.get(HEADERS["tax_category"]), TAX_CATEGORIES),
        "face_value": number(record.get(HEADERS["face_value"]), 10**12),
        "issue_size": number(record.get(HEADERS["issue_size"]), 10**16),
        "allotment_date": normalise_date(record.get(HEADERS["allotment"])),
        "maturity_date": "" if perpetual else normalise_date(record.get(HEADERS["redemption"])),
        "is_perpetual": 1 if perpetual else 0,
        "coupon_rate": normalise_coupon(record.get(HEADERS["coupon"]), frequency),
        "coupon_type": normalise_choice(record.get(HEADERS["coupon_type"]), COUPON_TYPES),
        "interest_frequency": frequency,
        "rating": rating,
        "rating_agency": agency,
        "issuer_ownership": normalise_choice(record.get(HEADERS["ownership"]), OWNERSHIPS),
        "status": normalise_status(record.get(HEADERS["status"])),
        "as_of": as_of,
    }  # fmt: skip


def convert_rows(rows, as_of: str) -> list[dict]:
    """Iterable of cell tuples (first = header) -> converted records, unique by ISIN, sorted by ISIN."""
    iterator = iter(rows)
    header = [clean(h) for h in next(iterator, ())]
    converted: dict[str, dict] = {}
    for cells in iterator:
        out = convert_row(dict(zip(header, cells, strict=False)), as_of)
        if out and out["isin"] not in converted:
            converted[out["isin"]] = out
    return [converted[k] for k in sorted(converted)]


def write_csv(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def read_xlsx(path: Path):
    from openpyxl import load_workbook  # dev dependency; imported lazily so tests of the pure parts need no workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        yield from workbook.worksheets[0].iter_rows(values_only=True)
    finally:
        workbook.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", type=Path)
    parser.add_argument("--as-of", default=date.today().isoformat(), help="YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    date.fromisoformat(args.as_of)
    records = convert_rows(read_xlsx(args.xlsx), args.as_of)
    write_csv(records, OUTPUT)
    print(f"wrote {len(records)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
