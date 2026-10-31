"""Mutual fund import from a CAMS/KFintech CAS PDF.

The functions here are pure (they only read attributes of casparser-shaped objects and of
mf_master / mutual fund rows), except `read_statement`, which is the only place that touches
casparser. The password and file are never stored or logged.
"""

import io
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.assets import MutualFundCreate

MAX_FILE_BYTES = 4 * 1024 * 1024
PURCHASE_TYPES = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "SWITCH_IN_MERGER"}
ZERO = Decimal("0.001")  # a running balance below this counts as empty

UNITS_DP = Decimal("0.001")
MONEY_DP = Decimal("0.01")
NAV_DP = Decimal("0.0001")


def _error(status: int, message: str, description: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"message": message, "description": description})


def read_statement(raw: bytes, password: str):
    """Parse a CAS PDF into casparser's CASData; raises HTTPException with message + description."""
    import casparser
    from casparser.exceptions import IncorrectPasswordError
    from casparser.types import CASData

    try:
        data = casparser.read_cas_pdf(io.BytesIO(raw), password, output="dict")
    except IncorrectPasswordError:
        raise _error(400, "Wrong password", "The CAS password is usually your PAN in capitals.")
    except Exception:
        return _read_mfcentral(raw, password)
    if not isinstance(data, CASData):
        if str(getattr(data, "file_type", "")) in ("NSDL", "CDSL", "FileType.NSDL", "FileType.CDSL"):
            raise _error(
                422,
                "Depository statements aren't supported yet",
                "Download a CAMS or KFintech CAS from MF Central.",
            )
        raise _error(422, "Couldn't read this statement", "Upload a CAMS or KFintech CAS PDF.")
    return data


def _read_mfcentral(raw: bytes, password: str):
    """Fallback for MF Central Detailed CAS PDFs, which casparser can't identify."""
    from app.services import mfcentral_cas

    unreadable = _error(422, "Couldn't read this statement", "Upload a CAMS or KFintech CAS PDF.")
    try:
        texts = mfcentral_cas.extract_page_texts(raw, password)
        if not mfcentral_cas.is_mfcentral(texts):
            raise unreadable
        data = mfcentral_cas.parse_mfcentral(texts)
    except HTTPException:
        raise
    except Exception:
        raise unreadable from None
    if not any(folio.schemes for folio in data.folios):
        raise unreadable
    return data


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _type_name(value) -> str:
    return str(getattr(value, "value", value))


def purchase_date_for(scheme) -> date | None:
    """Earliest purchase after the last time the running balance was ~0.

    Falls back to the valuation date when there are no transactions (summary CAS) or no
    qualifying purchase.
    """
    balance = Decimal(0)
    start = 0
    transactions = list(scheme.transactions or [])
    for index, txn in enumerate(transactions):
        if txn.balance is not None:
            balance = Decimal(txn.balance)
        elif txn.units is not None:
            balance += Decimal(txn.units)
        if abs(balance) < ZERO:
            start = index + 1
    dates = [
        d
        for txn in transactions[start:]
        if _type_name(txn.type) in PURCHASE_TYPES and (d := _as_date(txn.date))
    ]
    if dates:
        return min(dates)
    return _as_date(scheme.valuation.date)


def match_scheme(scheme, by_code: dict, by_isin: dict):
    """mf_master row for a CAS scheme: AMFI code first, then ISIN."""
    amfi = (scheme.amfi or "").strip()
    if amfi.isdigit() and int(amfi) in by_code:
        return by_code[int(amfi)]
    isin = (scheme.isin or "").strip().upper()
    return by_isin.get(isin) if isin else None


def master_lookups(masters: Iterable) -> tuple[dict, dict]:
    by_code, by_isin = {}, {}
    for m in masters:
        by_code[m.scheme_code] = m
        for isin in (m.isin_growth_payout, m.isin_reinvest):
            if isin:
                by_isin[isin.upper()] = m
    return by_code, by_isin


def cas_codes_and_isins(data) -> tuple[set[int], set[str]]:
    """AMFI codes and ISINs present in a statement (for the mf_master query)."""
    codes, isins = set(), set()
    for folio in data.folios:
        for scheme in folio.schemes:
            amfi = (scheme.amfi or "").strip()
            if amfi.isdigit():
                codes.add(int(amfi))
            if scheme.isin:
                isins.add(scheme.isin.strip().upper())
    return codes, isins


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    return str(error["msg"])


def build_rows(data, by_code: dict, by_isin: dict, existing_by_code: dict[int, list]) -> tuple[list[dict], int]:
    """Merge the statement's schemes into preview rows; returns (rows, hidden_zero)."""
    groups: dict[str, dict] = {}
    hidden_zero = 0
    for folio in data.folios:
        for scheme in folio.schemes:
            if abs(Decimal(scheme.close)) < ZERO:
                hidden_zero += 1
                continue
            master = match_scheme(scheme, by_code, by_isin)
            if master is not None:
                key = f"scheme:{master.scheme_code}"
            elif scheme.isin:
                key = f"isin:{scheme.isin.strip().upper()}"
            else:
                key = f"name:{scheme.scheme}"
            group = groups.setdefault(
                key, {"master": master, "items": [], "folios": [], "amcs": [], "isins": []}
            )
            group["items"].append(scheme)
            if folio.folio not in group["folios"]:
                group["folios"].append(folio.folio)
            group["amcs"].append(folio.amc)
            if scheme.isin:
                group["isins"].append(scheme.isin.strip().upper())

    rows = []
    for key, group in groups.items():
        rows.append(_row(key, group, existing_by_code))
    return rows, hidden_zero


def _transactions(items: list) -> list[dict]:
    """Purchases and redemptions of the merged schemes, sorted by date.

    The sign of the units decides the type (casparser's PURCHASE*/SWITCH_IN* are positive,
    REDEMPTION/SWITCH_OUT* negative). Rows without units or amount (stamp duty, STT, dividends,
    address changes) are dropped.
    """
    out = []
    for scheme in items:
        for txn in scheme.transactions or []:
            if not txn.units or not txn.amount:
                continue
            units, amount = Decimal(txn.units), Decimal(txn.amount)
            when = _as_date(txn.date)
            if units == 0 or amount == 0 or when is None:
                continue
            out.append(
                {
                    "date": when,
                    "type": "purchase" if units > 0 else "redemption",
                    "amount": abs(amount).quantize(MONEY_DP),
                    "units": abs(units).quantize(UNITS_DP),
                }
            )
    out.sort(key=lambda t: (t["date"], t["type"] != "purchase"))
    return out


MAX_TRANSACTIONS = 2000


def transaction_error(transactions: list, today: date | None = None) -> str | None:
    """First problem in a commit row's transactions, or None."""
    today = today or date.today()
    if len(transactions) > MAX_TRANSACTIONS:
        return f"Transactions: at most {MAX_TRANSACTIONS} per fund"
    for txn in transactions:
        if txn.date > today:
            return "Transaction date can't be in the future"
        if txn.amount <= 0:
            return "Transaction amount must be greater than 0"
        if txn.units <= 0:
            return "Transaction units must be greater than 0"
    return None


def save_transactions(db, holding_id: int, transactions: list) -> None:
    """Replace a holding's stored transactions with the given list (empty deletes them)."""
    from sqlalchemy import delete

    from app.models import MFTransaction

    db.execute(delete(MFTransaction).where(MFTransaction.mutual_fund_id == holding_id))
    db.add_all(
        MFTransaction(
            mutual_fund_id=holding_id, txn_date=t.date, kind=t.type,
            amount=t.amount.quantize(MONEY_DP), units=t.units.quantize(UNITS_DP),
        )  # fmt: skip
        for t in transactions
    )


def _row(key: str, group: dict, existing_by_code: dict[int, list]) -> dict:
    master = group["master"]
    items = group["items"]
    units = sum((Decimal(s.close) for s in items), Decimal(0)).quantize(UNITS_DP)
    costs = [s.valuation.cost for s in items]
    cost_missing = any(c is None or Decimal(c) <= 0 for c in costs)
    invested = sum((Decimal(c) for c in costs if c is not None), Decimal(0)).quantize(MONEY_DP)
    values = [s.valuation.value for s in items if s.valuation.value is not None]
    current_value = sum((Decimal(v) for v in values), Decimal(0)).quantize(MONEY_DP) if values else None
    avg_nav = (invested / units).quantize(NAV_DP) if units > 0 else Decimal(0)
    dates = [d for s in items if (d := purchase_date_for(s))]
    purchase = min(dates) if dates else None
    name = master.name if master else items[0].scheme.strip()

    issue = None
    if master is None:
        issue = "Not found in the AMFI scheme list"
    elif units <= 0:
        issue = "Closing units are not positive"
    elif any((getattr(s, "opening", None) or 0) > ZERO for s in items):
        issue = "Statement starts after the first purchase. Download it from your first investment date."
    elif cost_missing:
        issue = "The statement has no invested amount for this fund"
    elif purchase is None:
        issue = "The statement has no purchase date for this fund"
    else:
        try:
            MutualFundCreate(
                scheme_name=name[:200], scheme_code=master.scheme_code, category=master.category,
                units=units, avg_nav=avg_nav, invested_amount=invested, purchase_date=purchase,
            )  # fmt: skip
        except ValidationError as exc:
            issue = _first_error(exc)

    code = master.scheme_code if master else None
    existing = [
        {
            "id": h.id, "units": h.units, "invested_amount": h.invested_amount,
            "avg_nav": h.avg_nav, "purchase_date": h.purchase_date,
        }  # fmt: skip
        for h in (existing_by_code.get(code, []) if code is not None else [])
    ]
    return {
        "key": key,
        "scheme_code": code,
        "scheme_name": name,
        "amc": (master.amc if master and master.amc else None) or (group["amcs"][0] if group["amcs"] else None),
        "plan": master.plan if master and master.plan in ("direct", "regular") else None,
        "option": master.option if master and master.option in ("growth", "idcw", "bonus", "other") else None,
        "category": master.category if master else "other",
        "isin": group["isins"][0] if group["isins"] else None,
        "folios": group["folios"],
        "units": units,
        "invested_amount": invested,
        "avg_nav": avg_nav,
        "purchase_date": purchase,
        "current_value": current_value,
        "existing": existing,
        "transactions": _transactions(items),
        "importable": issue is None,
        "issue": issue,
    }  # fmt: skip
