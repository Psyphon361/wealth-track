"""MF Central "Detailed CAS" PDF parser (casparser 1.4.1 cannot identify these statements).

`parse_mfcentral` is a pure function over page text and returns casparser-shaped objects (only
the attributes cas_import.py reads). `extract_page_texts` is the only place that opens a PDF;
the file and password are never stored or logged.
"""

import io
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MARKER = "MFCentralDetailCAS"
OPENING_ZERO = Decimal("0.001")  # an opening balance below this counts as empty
MONEY_DP = Decimal("0.01")

_NUMBER = re.compile(r"^\(?-?[\d,]+(?:\.\d+)?\)?$")
_TXN = re.compile(r"^(\d{2}-[A-Za-z]{3}-\d{4})\s+(.*)$")
_FOLIO = re.compile(r"^FOLIO NO:\s*(.+)$")
_SCHEME = re.compile(r"^(?P<name>.*?)\s*\(Advisor:.*?ISIN:\s*(?P<isin>[A-Z0-9]{12})\b(?P<rest>.*)$")
_OPENING = re.compile(r"Opening Unit Balance:\s*(-?[\d,]+(?:\.\d+)?)")
_CLOSING = re.compile(
    r"Closing Unit Balance:\s*(-?[\d,]+(?:\.\d+)?).*?Valuation on\s+(\d{2}-[A-Za-z]{3}-\d{4})\s*:\s*INR\s*(-?[\d,]+(?:\.\d+)?)"
)
_PERIOD = re.compile(r"From Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})\s+To Date\s*:\s*(\d{2}-[A-Za-z]{3}-\d{4})")
_HEADER_PREFIXES = (
    "Consolidated Account Statement",
    "( From Date",
    MARKER,
    "SoA Holdings",
    "Transaction Amount",
    "(INR) Date",
)


@dataclass(frozen=True)
class Transaction:
    date: date
    type: str
    units: Decimal
    amount: Decimal
    balance: Decimal


@dataclass(frozen=True)
class Valuation:
    date: date | None
    cost: Decimal | None
    value: Decimal


@dataclass(frozen=True)
class Scheme:
    scheme: str
    isin: str
    close: Decimal
    opening: Decimal
    valuation: Valuation
    transactions: list[Transaction]
    amfi: str | None = None


@dataclass(frozen=True)
class Folio:
    folio: str
    amc: str
    schemes: list[Scheme] = field(default_factory=list)


@dataclass(frozen=True)
class Period:
    from_: date | None
    to: date | None


@dataclass(frozen=True)
class Statement:
    folios: list[Folio]
    statement_period: Period


def is_mfcentral(page_texts: list[str]) -> bool:
    return any(MARKER in text for text in page_texts)


def extract_page_texts(raw: bytes, password: str) -> list[str]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(io.BytesIO(raw), password=password or None)
    try:
        texts = []
        for index in range(len(doc)):
            page = doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    texts.append(textpage.get_text_bounded())
                finally:
                    textpage.close()
            finally:
                page.close()
        return texts
    finally:
        doc.close()


def _date(text: str) -> date:
    return datetime.strptime(text.title(), "%d-%b-%Y").date()


def _number(token: str) -> Decimal:
    negative = token.startswith("(") or "-" in token
    value = Decimal(token.strip("()").replace("-", "").replace(",", ""))
    return -value if negative else value


def _is_header(line: str) -> bool:
    return line.startswith(_HEADER_PREFIXES)


def _fifo_cost(transactions: list[Transaction]) -> Decimal:
    """Cost of the remaining units: outflows consume the oldest lots first."""
    lots: deque[list[Decimal]] = deque()  # [units, cost]
    for txn in transactions:
        if txn.units > 0:
            lots.append([txn.units, abs(txn.amount)])
            continue
        remaining = -txn.units
        while remaining > 0 and lots:
            lot = lots[0]
            if lot[0] <= remaining:
                remaining -= lot[0]
                lots.popleft()
            else:
                fraction = remaining / lot[0]
                lot[1] -= lot[1] * fraction
                lot[0] -= remaining
                remaining = Decimal(0)
    return sum((lot[1] for lot in lots), Decimal(0)).quantize(MONEY_DP)


def _transaction(line: str) -> Transaction | None:
    match = _TXN.match(line)
    if not match:
        return None
    tokens = match.group(2).split()
    if len(tokens) < 5 or not all(_NUMBER.match(t) for t in tokens[-4:]):
        return None
    try:
        amount, units, _price, balance = (_number(t) for t in tokens[-4:])
        day = _date(match.group(1))
    except (InvalidOperation, ValueError):
        return None
    if units == 0:
        return None
    return Transaction(day, "PURCHASE" if units > 0 else "REDEMPTION", units, amount, balance)


def parse_mfcentral(page_texts: list[str]) -> Statement:
    folios: list[Folio] = []
    period = Period(None, None)
    folio: Folio | None = None
    pending: dict | None = None  # scheme being read
    previous = ""

    for text in page_texts:
        if period.from_ is None and (found := _PERIOD.search(text)):
            period = Period(_date(found.group(1)), _date(found.group(2)))
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or _is_header(line):
                continue
            if found := _FOLIO.match(line):
                folio = Folio(folio=found.group(1).strip(), amc=previous)
                folios.append(folio)
                pending = None
            elif folio is not None and (found := _SCHEME.match(line)):
                pending = {
                    "name": found.group("name").strip(),
                    "isin": found.group("isin"),
                    "opening": Decimal(0),
                    "transactions": [],
                }
                if opening := _OPENING.search(found.group("rest")):
                    pending["opening"] = _number(opening.group(1))
            elif pending is not None:
                if opening := _OPENING.search(line):
                    pending["opening"] = _number(opening.group(1))
                elif closing := _CLOSING.search(line):
                    transactions = pending["transactions"]
                    has_opening = pending["opening"] >= OPENING_ZERO
                    cost = None if has_opening else _fifo_cost(transactions)
                    folio.schemes.append(
                        Scheme(
                            scheme=pending["name"],
                            isin=pending["isin"],
                            close=_number(closing.group(1)),
                            opening=pending["opening"],
                            valuation=Valuation(_date(closing.group(2)), cost, _number(closing.group(3))),
                            transactions=transactions,
                        )
                    )
                    pending = None
                elif (txn := _transaction(line)) is not None:
                    pending["transactions"].append(txn)
            previous = line
    return Statement(folios=folios, statement_period=period)
