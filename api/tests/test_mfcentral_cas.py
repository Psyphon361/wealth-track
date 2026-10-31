from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services import cas_import, mfcentral_cas

HEADER = """Consolidated Account Statement
( From Date : 01-Jan-2025 To Date : 31-Oct-2026 )
MFCentralDetailCAS_v1.2_123-456_01-Jan-2025_31-Oct-2026 _-31/10/2026 6:48:38am Page {n} of 9
SoA Holdings Demat Holdings
Transaction Amount (INR) Units Price
(INR) Date Unit Balance
"""

PAGE_ONE = (
    HEADER.format(n=1)
    + """Allocation by Asset Class
Equity 100.00%
Alpha Mutual Fund
FOLIO NO: 31000000001
Alpha Small Cap Fund - Direct Plan Growth (Advisor: INZ000000000/DIRECT) ISIN: INF000A01AA1
KYC : OK
Opening Unit Balance: 0.000
10-NOV-2025 New Purchase 29,998.50 639.491 46.91 639.491
23-OCT-2025 Address Updated from CVL Data 0.00 0.000 0.00 639.491
"""
)
PAGE_TWO = (
    HEADER.format(n=2)
    + """23-DEC-2025 Additional Purchase 14,999.25 320.291 46.83 959.782
Closing Unit Balance: 959.782 Nav as on 30-OCT-2026: INR 51.10 Valuation on 31-Oct-2026 : INR 49,044.86
Beta Mutual Fund
FOLIO NO: 8938678
Beta Small Cap Fund-Direct Plan-Growth (Advisor: INZ000000000/INZ000000000 ISIN: INF000B01BB2 Opening Unit Balance: 0.000
13-MAR-2026 Systematic Investment Existing Folio with SIP (1) 22,498.88 535.943 41.98 535.943
18-MAY-2026 Net Systematic Purchase Instalment No - 1 via Online 22,498.88 434.400 51.79 970.343
Closing Unit Balance: 970.343 Nav as on 30-OCT-2026: INR 53.227 Valuation on 31-Oct-2026 : INR 51,647.93
#IDCW - Income Distribution cum Capital Withdrawal
"""
)


def parse(*pages):
    return mfcentral_cas.parse_mfcentral(list(pages))


def test_is_mfcentral():
    assert mfcentral_cas.is_mfcentral([PAGE_ONE])
    assert not mfcentral_cas.is_mfcentral(["Consolidated Account Statement CAMSCASWS"])


def test_two_variants_and_page_break():
    data = parse(PAGE_ONE, PAGE_TWO)
    assert data.statement_period.from_ == date(2025, 1, 1)
    assert data.statement_period.to == date(2026, 10, 31)
    assert [(f.folio, f.amc) for f in data.folios] == [
        ("31000000001", "Alpha Mutual Fund"),
        ("8938678", "Beta Mutual Fund"),
    ]
    alpha = data.folios[0].schemes[0]
    assert alpha.scheme == "Alpha Small Cap Fund - Direct Plan Growth"
    assert alpha.isin == "INF000A01AA1"
    assert alpha.amfi is None
    assert alpha.close == Decimal("959.782")
    assert alpha.valuation.date == date(2026, 10, 31)
    assert alpha.valuation.value == Decimal("49044.86")
    assert [t.date for t in alpha.transactions] == [date(2025, 11, 10), date(2025, 12, 23)]
    assert alpha.valuation.cost == Decimal("44997.75")

    beta = data.folios[1].schemes[0]
    assert beta.scheme == "Beta Small Cap Fund-Direct Plan-Growth"
    assert beta.isin == "INF000B01BB2"
    assert beta.opening == 0
    assert beta.transactions[0].amount == Decimal("22498.88")
    assert beta.transactions[0].balance == Decimal("535.943")
    assert beta.valuation.cost == Decimal("44997.76")


def test_zero_unit_rows_skipped():
    alpha = parse(PAGE_ONE, PAGE_TWO).folios[0].schemes[0]
    assert len(alpha.transactions) == 2
    assert all(t.type == "PURCHASE" and t.units > 0 for t in alpha.transactions)


def test_fifo_cost_with_redemption():
    text = HEADER.format(n=1) + """Alpha Mutual Fund
FOLIO NO: 1
Alpha Fund (Advisor: INZ000000000/DIRECT) ISIN: INF000A01AA1
Opening Unit Balance: 0.000
01-JAN-2025 New Purchase 1,000.00 100.000 10.00 100.000
01-FEB-2025 Additional Purchase 2,000.00 100.000 20.00 200.000
01-MAR-2025 Redemption (1,500.00) (150.000) 15.00 50.000
Closing Unit Balance: 50.000 Nav as on 30-OCT-2026: INR 30.00 Valuation on 31-Oct-2026 : INR 1,500.00
"""
    scheme = parse(text).folios[0].schemes[0]
    redemption = scheme.transactions[-1]
    assert redemption.type == "REDEMPTION"
    assert redemption.units == Decimal("-150.000")
    # 100 units of the first lot go, then 50 of the 100 units costing 2,000
    assert scheme.valuation.cost == Decimal("1000.00")


def test_opening_balance_means_unknown_cost():
    text = HEADER.format(n=1) + """Alpha Mutual Fund
FOLIO NO: 1
Alpha Fund (Advisor: INZ000000000/DIRECT) ISIN: INF000A01AA1
Opening Unit Balance: 25.500
01-JAN-2025 Additional Purchase 1,000.00 100.000 10.00 125.500
Closing Unit Balance: 125.500 Nav as on 30-OCT-2026: INR 30.00 Valuation on 31-Oct-2026 : INR 3,765.00
"""
    scheme = parse(text).folios[0].schemes[0]
    assert scheme.opening == Decimal("25.500")
    assert scheme.valuation.cost is None


def master(code, isin):
    return SimpleNamespace(
        scheme_code=code, name=f"Fund {code}", amc="Test AMC Mutual Fund", category="equity",
        plan="direct", option="growth", isin_growth_payout=isin, isin_reinvest=None,
    )  # fmt: skip


def test_build_rows_on_parsed_statement():
    opening_page = HEADER.format(n=3) + """Gamma Mutual Fund
FOLIO NO: 5
Gamma Fund (Advisor: INZ000000000/DIRECT) ISIN: INF000C01CC3
Opening Unit Balance: 10.000
01-JAN-2025 Additional Purchase 1,000.00 100.000 10.00 110.000
Closing Unit Balance: 110.000 Nav as on 30-OCT-2026: INR 30.00 Valuation on 31-Oct-2026 : INR 3,300.00
"""
    data = parse(PAGE_ONE, PAGE_TWO, opening_page)
    by_code, by_isin = cas_import.master_lookups(
        [master(1, "INF000A01AA1"), master(2, "INF000B01BB2"), master(3, "INF000C01CC3")]
    )
    rows, hidden = cas_import.build_rows(data, by_code, by_isin, {})
    by_key = {r["key"]: r for r in rows}
    assert hidden == 0

    alpha = by_key["scheme:1"]
    assert alpha["importable"] and alpha["issue"] is None
    assert alpha["units"] == Decimal("959.782")
    assert alpha["invested_amount"] == Decimal("44997.75")
    assert alpha["purchase_date"] == date(2025, 11, 10)

    gamma = by_key["scheme:3"]
    assert not gamma["importable"]
    assert gamma["issue"] == (
        "Statement starts after the first purchase. Download it from your first investment date."
    )
