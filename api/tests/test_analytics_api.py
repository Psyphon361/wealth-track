"""GET /api/analytics/overview through the endpoint: real rows of all ten asset types in SQLite,
so the real read schemas and computed fields feed the maths. Every expected figure is a
hand-worked literal; `today` is fixed to 2026-11-02.

User A's active holdings (current value):
  FD   F1 HDFC Bank "Joint" 300,000 (issuer 1) | F2 "HDFC Ltd" payout 300,000 (issuer 2, merged
       into 1) | F3 "SURYODAY Small  Finance Bank Limited" payout 200,000 (matched by name) |
       F4 "Local Co-op Bank" 100,000 (no issuer)                                   = 900,000
  RD   R1 "SBI" 5,000 (matched by short name)                                      =   5,000
  Stock S1 Reliance 10 x 2,500 | S2 Gold BeES ETF 100 x 60 | S3 Nifty BeES ETF 10 x 250 |
       S4 unpriced stock at cost 1,000                                             =  34,500
  Bond B1 NHAI 10,000 | B2 SGB (master says sgb) 31,000 | (B3 matured, excluded)   =  41,000
  MF   M1 equity 100 x 50 | M2 ELSS 200 x 40 | M3 liquid fund with no NAV, 1,000   =  14,000
  NPS  N1 Tier I E 100 x 30 | N2 Tier II G with no NAV, 1,500                      =   4,500
  Gold G1 916 jewellery 10 g x 6,000 | G2 digital silver with no rate, 8,000       =  68,000
  Cash C1 25,000 | C2 5,000 (stale)                                                =  30,000
  PF   P1 EPF 100,000 | P2 PPF 200,000                                             = 300,000
  Other O1 80,000 | O2 20,000 (stale)                                              = 100,000
  Total 1,497,000
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    Bond,
    Cash,
    FdIssuerMaster,
    FixedDeposit,
    Gold,
    GoldRateHistory,
    GoldRateLatest,
    MFMaster,
    MFNavHistory,
    MFNavLatest,
    MFTransaction,
    MutualFund,
    Nps,
    NpsMaster,
    NpsNavLatest,
    Other,
    Pf,
    RecurringDeposit,
    Stock,
    StockMaster,
    StockPriceLatest,
)
from app.routers import analytics as analytics_router
from app.routers import portfolio
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 2)
TYPES = ["fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other"]


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def fixed_today(monkeypatch):
    """The analytics route and /api/dashboard both value holdings on 2026-11-02."""
    monkeypatch.setattr(analytics_router, "date", _FixedDate)
    original = portfolio.load_groups
    monkeypatch.setattr(
        portfolio, "load_groups", lambda db, user_id, today=None: original(db, user_id, TODAY)
    )


@pytest.fixture
def tables(client, auth_engine, fixed_today):  # noqa: F811
    """Master tables the route reads (bond_master has a Postgres-only ARRAY column, so the three
    columns the route reads are created by hand)."""
    Base.metadata.create_all(
        auth_engine,
        tables=[
            m.__table__
            for m in (StockMaster, StockPriceLatest, MFMaster, MFNavHistory, FdIssuerMaster)
        ]
        + [GoldRateHistory.__table__],
    )
    with auth_engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE bond_master (id INTEGER PRIMARY KEY, bond_type VARCHAR, issuer VARCHAR)")
        )


def _utc(year, month, day):
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


def _masters(session):
    session.add_all(
        [
            FdIssuerMaster(
                id=1, code="hdfc-bank", name="HDFC Bank Limited", short_name="HDFC Bank",
                category="private_sector", dicgc_insured=True,
            ),
            FdIssuerMaster(
                id=2, code="hdfc-ltd", name="Housing Development Finance Corporation Limited",
                short_name="HDFC Ltd", category="hfc", merged_into_id=1,
            ),
            FdIssuerMaster(
                id=3, code="suryoday", name="Suryoday Small Finance Bank Limited",
                short_name="Suryoday", category="small_finance", dicgc_insured=True,
            ),
            FdIssuerMaster(
                id=4, code="sbi", name="State Bank of India", short_name="SBI",
                category="public_sector", dicgc_insured=True,
            ),
            StockMaster(
                id=1, isin="INE002A01018", kind="stock", name="Reliance Industries Ltd",
                nse_symbol="RELIANCE",
            ),
            StockMaster(
                id=2, isin="INF0GOLD0001", kind="etf", name="Nippon India ETF Gold BeES",
                nse_symbol="GOLDBEES",
            ),
            StockMaster(
                id=3, isin="INF0NIFTY001", kind="etf", name="Nippon India ETF Nifty 50 BeES",
                nse_symbol="NIFTYBEES",
            ),
            StockMaster(id=4, isin="INE000U00014", kind="stock", name="Unpriced Ltd"),
            MFMaster(
                scheme_code=120503, name="HDFC Flexi Cap Fund - Growth", amc="HDFC Mutual Fund",
                amfi_category="Equity Scheme - Flexi Cap Fund", category="equity",
            ),
            MFMaster(
                scheme_code=120504, name="Axis ELSS Tax Saver Fund - Growth",
                amc="Axis Mutual Fund", amfi_category="Equity Scheme - ELSS", category="elss",
            ),
            MFMaster(
                scheme_code=120505, name="ICICI Prudential Liquid Fund - Growth",
                amc="ICICI Prudential Mutual Fund", amfi_category="Debt Scheme - Liquid Fund",
                category="liquid",
            ),
            NpsMaster(
                scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E",
            ),
            NpsMaster(
                scheme_id="SM002010", pfm_code="PFM002", pfm_name="HDFC Pension Management",
                scheme_name="HDFC PENSION FUND SCHEME G - TIER II", tier="II", asset_class="G",
            ),
        ]
    )
    session.flush()
    session.add_all(
        [
            StockPriceLatest(
                master_id=1, price=2500, prev_close=2450, price_time=_utc(2026, 10, 30),
                source="bhavcopy",
            ),
            StockPriceLatest(
                master_id=2, price=60, prev_close=59, price_time=_utc(2026, 10, 31),
                source="bhavcopy",
            ),
            StockPriceLatest(
                master_id=3, price=250, prev_close=248, price_time=_utc(2026, 10, 29),
                source="bhavcopy",
            ),
            MFNavLatest(scheme_code=120503, nav=50, nav_date=date(2026, 11, 1)),
            MFNavLatest(scheme_code=120504, nav=40, nav_date=date(2026, 10, 30)),
            NpsNavLatest(scheme_id="SM001003", nav=30, nav_date=date(2026, 10, 31)),
            GoldRateLatest(
                metal="gold", purity="916", rate_per_gram=6000, rate_date=TODAY, session="PM",
                source="ibja",
            ),
        ]
    )


def _fd(user_id, bank, principal, *, label=None, issuer_id=None, payout="cumulative",
        start=TODAY, years=1, deleted_at=None):  # fmt: skip
    return FixedDeposit(
        user_id=user_id, bank=bank, label=label, issuer_id=issuer_id, principal=principal,
        rate=8, start_date=start, compounding="quarterly", payout_type=payout,
        tenure_years=years, deleted_at=deleted_at,
    )


def _holdings_a(uid):
    """User A's active holdings in per-table insertion order (so ids are 1, 2, ...)."""
    return [
        _fd(uid, "HDFC Bank", 300000, label="Joint", issuer_id=1),
        _fd(uid, "HDFC Ltd", 300000, issuer_id=2, payout="payout"),
        _fd(uid, "SURYODAY Small  Finance Bank Limited", 200000, payout="payout",
            start=date(2025, 12, 2)),
        _fd(uid, "Local Co-op Bank", 100000),
        RecurringDeposit(
            user_id=uid, bank="SBI", monthly_instalment=5000, rate=6, start_date=TODAY,
            compounding="quarterly", tenure_months=3,
        ),
        Stock(user_id=uid, name="Reliance Industries", symbol="RELIANCE", exchange="NSE",
              master_id=1, quantity=10, avg_buy_price=2000, buy_date=TODAY),
        Stock(user_id=uid, name="Gold BeES", exchange="NSE", master_id=2, quantity=100,
              avg_buy_price=50, buy_date=TODAY),
        Stock(user_id=uid, name="Nifty BeES", exchange="NSE", master_id=3, quantity=10,
              avg_buy_price=200, buy_date=TODAY),
        Stock(user_id=uid, name="Unpriced Ltd", exchange="NSE", master_id=4, quantity=10,
              avg_buy_price=100, buy_date=TODAY),
        Bond(
            user_id=uid, name="NHAI 2030", issuer="NHAI", bond_type="tax_free", master_id=1,
            quantity=10, face_value=1000, purchase_price=1000, invested_amount=10000,
            purchase_date=TODAY, ytm=7, maturity_date=date(2027, 1, 15),
        ),
        Bond(
            user_id=uid, name="SGB 2027", issuer="RBI", bond_type="government", master_id=2,
            quantity=5, face_value=6000, purchase_price=6200, invested_amount=31000,
            purchase_date=TODAY, ytm=Decimal("2.5"), maturity_date=date(2027, 6, 1),
        ),
        Bond(
            user_id=uid, name="Old Bond", issuer="Acme Finance", bond_type="corporate",
            quantity=10, face_value=1000, purchase_price=1000, invested_amount=10000,
            purchase_date=date(2025, 10, 1), ytm=8, maturity_date=date(2026, 10, 1),
        ),
        MutualFund(
            user_id=uid, scheme_name="HDFC Flexi Cap Fund - Growth", scheme_code=120503,
            category="equity", units=100, avg_nav=40, invested_amount=4000,
            purchase_date=date(2024, 1, 1),
        ),
        MutualFund(
            user_id=uid, scheme_name="Axis ELSS Tax Saver Fund - Growth", scheme_code=120504,
            category="elss", units=200, avg_nav=30, invested_amount=6000,
            purchase_date=date(2024, 6, 10),
        ),
        MutualFund(
            user_id=uid, scheme_name="ICICI Prudential Liquid Fund - Growth", scheme_code=120505,
            category="liquid", units=10, avg_nav=100, invested_amount=1000,
            purchase_date=date(2024, 1, 1),
        ),
        Nps(user_id=uid, scheme_id="SM001003", units=100, contributed=2500,
            start_date=date(2024, 1, 1)),
        Nps(user_id=uid, scheme_id="SM002010", units=50, contributed=1500,
            start_date=date(2024, 1, 1)),
        Gold(user_id=uid, name="Wedding set", form="jewellery", metal="gold", purity="916",
             weight_grams=10, purchase_date=date(2024, 1, 1), invested_amount=50000),
        Gold(user_id=uid, name="Silver digital", form="digital", metal="silver", purity="999",
             weight_grams=100, purchase_date=date(2024, 1, 1), invested_amount=8000),
        Cash(user_id=uid, name="Salary account", kind="savings", balance=25000,
             balance_date=TODAY),
        Cash(user_id=uid, name="Old wallet", kind="cash", balance=5000,
             balance_date=date(2026, 3, 1)),
        Pf(user_id=uid, name="Employer EPF", kind="epf", balance=100000, balance_date=TODAY,
           interest_rate=Decimal("8.25")),
        Pf(user_id=uid, name="PPF", kind="ppf", balance=200000, balance_date=TODAY,
           interest_rate=Decimal("7.1"), opened_on=date(2011, 4, 10)),
        Other(user_id=uid, name="Bitcoin", category="Crypto", current_value=80000,
              value_date=TODAY),
        Other(user_id=uid, name="Old painting", category="Art", current_value=20000,
              value_date=date(2025, 12, 1)),
    ]


@pytest.fixture
def seeded(client, users, tables, auth_engine):  # noqa: F811
    """User A's portfolio, a soft-deleted extra set for A, and a small portfolio for user B."""
    a, a_id, b, _ = users
    b_id = users[3]
    gone = datetime(2026, 10, 20, tzinfo=timezone.utc)
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        _masters(session)
        session.flush()
        session.execute(
            text(
                "INSERT INTO bond_master (id, bond_type, issuer) VALUES "
                "(1, 'tax_free', 'National Highways Authority of India'), "
                "(2, 'sgb', 'Government of India')"
            )
        )
        session.add_all(_holdings_a(a_id))
        session.flush()
        elss = session.query(MutualFund).filter_by(scheme_code=120504).one()
        session.add_all(
            [
                MFTransaction(
                    mutual_fund_id=elss.id, txn_date=date(2023, 1, 10), kind="purchase",
                    amount=3000, units=100,
                ),
                MFTransaction(
                    mutual_fund_id=elss.id, txn_date=date(2024, 6, 10), kind="purchase",
                    amount=3000, units=100,
                ),
                # Soft-deleted rows of A, and B's own holdings: none may reach A's figures.
                _fd(a_id, "HDFC Bank", 777000, label="Deleted", issuer_id=1, deleted_at=gone),
                Cash(user_id=a_id, name="Deleted cash", kind="cash", balance=12345,
                     balance_date=TODAY, deleted_at=gone),
                Stock(user_id=a_id, name="Deleted stock", exchange="NSE", master_id=1,
                      quantity=1, avg_buy_price=1, buy_date=TODAY, deleted_at=gone),
                _fd(b_id, "HDFC Bank", 400000, label="B deposit", issuer_id=1),
                Cash(user_id=b_id, name="B cash", kind="savings", balance=100000,
                     balance_date=TODAY),
            ]
        )
        session.commit()
    return a, b


def _overview(client, headers) -> dict:
    response = client.get("/api/analytics/overview", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _classes(view: dict) -> dict[str, dict]:
    return {c["class"]: c for c in view["classes"]}


# --- Auth, empty, scoping ----------------------------------------------------------------------


def test_requires_bearer(client):
    assert client.get("/api/analytics/overview").status_code == 401
    bad = {"Authorization": "Bearer nonsense"}
    assert client.get("/api/analytics/overview", headers=bad).status_code == 401


def test_empty_portfolio_returns_zeros_and_empty_lists(client, users, tables):  # noqa: F811
    body = _overview(client, users[0])
    assert body["as_of"] == "2026-11-02"
    assert body["allocation"] == {
        "including_retirement": {"total": 0, "classes": []},
        "excluding_retirement": {"total": 0, "classes": []},
        "retirement_value": 0,
        "retirement_percent": 0,
    }
    conc = body["concentration"]
    assert conc["total"] == 0 and conc["top_holdings"] == [] and conc["flags"] == []
    assert [r["key"] for r in conc["rollups"]] == [
        "stock", "mf_amc", "bank", "bond_issuer", "nps_pfm"
    ]
    assert all(r["total"] == 0 and r["bars"] == [] for r in conc["rollups"])
    liquidity = body["liquidity"]
    assert liquidity["total"] == 0
    assert [(b["key"], b["amount"], b["percent"]) for b in liquidity["buckets"]] == [
        ("instant", 0, 0), ("days", 0, 0), ("breakable", 0, 0), ("illiquid", 0, 0),
        ("locked", 0, 0), ("not_classified", 0, 0),
    ]  # fmt: skip
    coming = body["coming_up"]
    assert coming["next_30_days"] == {"until": "2026-12-02", "total": 0, "rows": []}
    assert coming["next_90_days"] == {"until": "2027-01-31", "total": 0, "rows": []}
    assert coming["next_180_days"] == {"until": "2027-05-01", "total": 0, "rows": []}
    assert coming["next_12_months"] == {"until": "2027-11-02", "total": 0, "rows": []}
    assert coming["already_matured"] == {"count": 0, "rows": []}
    assert body["bank_safety"] == {
        "limit": 500000, "total_deposits": 0, "insured": 0, "uninsured_excess": 0,
        "unknown_amount": 0, "sovereign_amount": 0, "banks": [],
    }  # fmt: skip
    assert body["data_health"] == {
        "at_cost": {"count": 0, "items": []},
        "stale_balances": {"count": 0, "items": []},
        "matured_open": {"count": 0, "items": []},
        "latest": {"stock_price": None, "mf_nav": None, "nps_nav": None, "gold_rate": None},
    }


def test_totals_reconcile_with_dashboard(client, seeded):
    a, _ = seeded
    dashboard = client.get("/api/dashboard", headers=a).json()
    assert dashboard["total_current"] == 1497000
    body = _overview(client, a)
    assert body["allocation"]["including_retirement"]["total"] == dashboard["total_current"]
    assert body["liquidity"]["total"] == dashboard["total_current"]
    assert body["concentration"]["total"] == dashboard["total_current"]
    classes = body["allocation"]["including_retirement"]["classes"]
    assert sum(c["value"] for c in classes) == 1497000
    assert sum(b["amount"] for b in body["liquidity"]["buckets"]) == 1497000
    # Retirement (EPF 100,000 + PPF 200,000 + NPS Tier I 3,000) comes out of the other view.
    assert body["allocation"]["retirement_value"] == 303000
    assert body["allocation"]["excluding_retirement"]["total"] == 1194000


def test_other_user_and_soft_deleted_holdings_excluded(client, seeded):
    a, b = seeded
    body = _overview(client, a)
    names = {
        h["name"]
        for c in body["allocation"]["including_retirement"]["classes"]
        for t in c["types"]
        for h in t["holdings"]
    }
    assert not names & {"Deleted cash", "Deleted stock", "HDFC Bank · Deleted", "B cash"}
    assert not any("B deposit" in n for n in names)
    hdfc = next(x for x in body["bank_safety"]["banks"] if x["key"] == "issuer:1")
    assert hdfc["total"] == 600000

    other = _overview(client, b)
    assert other["allocation"]["including_retirement"]["total"] == 500000
    assert other["liquidity"]["total"] == 500000
    by_class = _classes(other["allocation"]["including_retirement"])
    assert (by_class["debt"]["value"], by_class["cash"]["value"]) == (400000, 100000)
    (bank,) = other["bank_safety"]["banks"]
    assert (bank["key"], bank["total"], bank["insured"], bank["excess"]) == (
        "issuer:1", 400000, 400000, 0
    )
    assert other["data_health"]["at_cost"]["count"] == 0
    assert other["coming_up"]["already_matured"]["count"] == 0


# --- Allocation --------------------------------------------------------------------------------


def test_allocation_classes_types_and_percents(client, seeded):
    body = _overview(client, seeded[0])["allocation"]
    including = body["including_retirement"]
    assert [c["class"] for c in including["classes"]] == ["equity", "debt", "gold", "cash", "other"]
    assert "class_" not in including["classes"][0]
    by_class = _classes(including)
    assert {k: (c["label"], c["value"], c["percent"]) for k, c in by_class.items()} == {
        "equity": ("Equity", 44500, 2.97),
        "debt": ("Debt", 1217500, 81.33),
        "gold": ("Gold & silver", 105000, 7.01),
        "cash": ("Cash", 30000, 2.0),
        "other": ("Other", 100000, 6.68),
    }
    types = {
        k: [(t["type"], t["value"], t["percent"]) for t in c["types"]] for k, c in by_class.items()
    }
    assert types["equity"] == [("stock", 28500, 1.9), ("mf", 13000, 0.87), ("nps", 3000, 0.2)]
    assert types["debt"] == [
        ("fd", 900000, 60.12), ("pf", 300000, 20.04), ("bond", 10000, 0.67),
        ("rd", 5000, 0.33), ("nps", 1500, 0.1), ("mf", 1000, 0.07),
    ]  # fmt: skip
    assert types["gold"] == [("gold", 68000, 4.54), ("bond", 31000, 2.07), ("stock", 6000, 0.4)]
    gold_type = by_class["gold"]["types"][0]
    assert [(h["name"], h["value"], h["percent"]) for h in gold_type["holdings"]] == [
        ("Wedding set", 60000, 4.01), ("Silver digital", 8000, 0.53)
    ]

    excluding = _classes(body["excluding_retirement"])
    assert {k: (c["value"], c["percent"]) for k, c in excluding.items()} == {
        "equity": (41500, 3.48),
        "debt": (917500, 76.84),
        "gold": (105000, 8.79),
        "cash": (30000, 2.51),
        "other": (100000, 8.38),
    }
    assert (body["retirement_value"], body["retirement_percent"]) == (303000, 20.24)


def test_nps_sgb_and_etf_classification_from_real_masters(client, seeded):
    by_class = _classes(_overview(client, seeded[0])["allocation"]["including_retirement"])

    def names(cls, asset_type):
        (group,) = [t for t in by_class[cls]["types"] if t["type"] == asset_type]
        return [h["name"] for h in group["holdings"]]

    # NPS asset class E is equity, G is debt (the Tier II scheme).
    assert names("equity", "nps") == ["SBI PENSION FUND SCHEME E - TIER I"]
    assert names("debt", "nps") == ["HDFC PENSION FUND SCHEME G - TIER II"]
    # The bond whose master says sgb is gold; the tax-free bond is debt.
    assert names("gold", "bond") == ["SGB 2027"]
    assert names("debt", "bond") == ["NHAI 2030"]
    # A gold ETF is gold, a Nifty ETF is equity, a plain stock is equity.
    assert names("gold", "stock") == ["Gold BeES"]
    assert names("equity", "stock") == ["Reliance Industries", "Nifty BeES", "Unpriced Ltd"]
    # Funds: AMFI categories decide (flexi cap and ELSS equity, liquid debt).
    assert names("equity", "mf") == [
        "Axis ELSS Tax Saver Fund - Growth", "HDFC Flexi Cap Fund - Growth"
    ]
    assert names("debt", "mf") == ["ICICI Prudential Liquid Fund - Growth"]


def test_holding_name_renders_for_all_ten_types(client, seeded):
    including = _overview(client, seeded[0])["allocation"]["including_retirement"]
    by_type: dict[str, set[str]] = {}
    for cls in including["classes"]:
        for group in cls["types"]:
            by_type.setdefault(group["type"], set()).update(h["name"] for h in group["holdings"])
    assert set(by_type) == set(TYPES)
    assert by_type == {
        "fd": {
            "HDFC Bank · Joint", "HDFC Ltd", "SURYODAY Small  Finance Bank Limited",
            "Local Co-op Bank",
        },
        "rd": {"SBI"},
        "stock": {"Reliance Industries", "Gold BeES", "Nifty BeES", "Unpriced Ltd"},
        "bond": {"NHAI 2030", "SGB 2027"},
        "mf": {
            "HDFC Flexi Cap Fund - Growth", "Axis ELSS Tax Saver Fund - Growth",
            "ICICI Prudential Liquid Fund - Growth",
        },
        "nps": {"SBI PENSION FUND SCHEME E - TIER I", "HDFC PENSION FUND SCHEME G - TIER II"},
        "gold": {"Wedding set", "Silver digital"},
        "cash": {"Salary account", "Old wallet"},
        "pf": {"Employer EPF", "PPF"},
        "other": {"Bitcoin", "Old painting"},
    }


# --- Concentration -----------------------------------------------------------------------------


def test_concentration_top_holdings_rollups_and_flags(client, seeded):
    conc = _overview(client, seeded[0])["concentration"]
    assert [(h["type"], h["id"], h["name"], h["value"], h["percent"]) for h in conc["top_holdings"]] == [
        ("fd", 1, "HDFC Bank · Joint", 300000, 20.04),
        ("fd", 2, "HDFC Ltd", 300000, 20.04),
        ("fd", 3, "SURYODAY Small  Finance Bank Limited", 200000, 13.36),
        ("pf", 2, "PPF", 200000, 13.36),
        ("fd", 4, "Local Co-op Bank", 100000, 6.68),
        ("pf", 1, "Employer EPF", 100000, 6.68),
        ("other", 1, "Bitcoin", 80000, 5.34),
        ("gold", 1, "Wedding set", 60000, 4.01),
        ("bond", 2, "SGB 2027", 31000, 2.07),
        ("cash", 1, "Salary account", 25000, 1.67),
    ]  # fmt: skip

    rollups = {r["key"]: r for r in conc["rollups"]}

    def bars(key):
        return [(b["key"], b["label"], b["value"], b["percent"], b["passive"]) for b in rollups[key]["bars"]]

    assert rollups["stock"]["total"] == 34500
    assert bars("stock") == [
        ("master:1", "Reliance Industries Ltd", 25000, 72.46, False),
        ("master:2", "Nippon India ETF Gold BeES", 6000, 17.39, True),
        ("master:3", "Nippon India ETF Nifty 50 BeES", 2500, 7.25, True),
        ("master:4", "Unpriced Ltd", 1000, 2.9, False),
    ]
    assert rollups["mf_amc"]["total"] == 14000
    assert bars("mf_amc") == [
        ("axis mutual fund", "Axis Mutual Fund", 8000, 57.14, False),
        ("hdfc mutual fund", "HDFC Mutual Fund", 5000, 35.71, False),
        ("icici prudential mutual fund", "ICICI Prudential Mutual Fund", 1000, 7.14, False),
    ]
    # HDFC Ltd rolls up into HDFC Bank through the merge; the RD and the name-matched FD hit
    # their issuers; the unlisted bank stays under its own name.
    assert rollups["bank"]["total"] == 905000
    assert bars("bank") == [
        ("issuer:1", "HDFC Bank", 600000, 66.3, False),
        ("issuer:3", "Suryoday", 200000, 22.1, False),
        ("name:local co-op bank", "Local Co-op Bank", 100000, 11.05, False),
        ("issuer:4", "SBI", 5000, 0.55, False),
    ]
    assert rollups["bond_issuer"]["total"] == 41000
    assert bars("bond_issuer") == [
        ("government of india", "Government of India", 31000, 75.61, False),
        (
            "national highways authority of india",
            "National Highways Authority of India", 10000, 24.39, False,
        ),
    ]  # fmt: skip
    assert rollups["nps_pfm"]["total"] == 4500
    assert bars("nps_pfm") == [
        ("sbi pension funds", "SBI Pension Funds", 3000, 66.67, False),
        ("hdfc pension management", "HDFC Pension Management", 1500, 33.33, False),
    ]

    assert [(f["kind"], f["key"], f["label"], f["value"], f["percent"], f["threshold"]) for f in conc["flags"]] == [
        ("single_stock", "master:1", "Reliance Industries Ltd", 25000, 56.18, 10),
        ("amc", "axis mutual fund", "Axis Mutual Fund", 8000, 57.14, 30),
        ("amc", "hdfc mutual fund", "HDFC Mutual Fund", 5000, 35.71, 30),
    ]  # fmt: skip


# --- Liquidity ---------------------------------------------------------------------------------


def test_liquidity_buckets_with_elss_lots(client, seeded):
    liquidity = _overview(client, seeded[0])["liquidity"]
    assert liquidity["total"] == 1497000
    assert [(b["key"], b["label"], b["amount"], b["percent"]) for b in liquidity["buckets"]] == [
        ("instant", "Instant", 30000, 2.0),
        # Stocks 34,500 + flexi cap 5,000 + liquid fund 1,000 + ELSS lot bought 2023-01-10, free
        # since 2026-01-10 (4,000) + NPS Tier II 1,500 + digital silver 8,000.
        ("days", "1-3 days", 54000, 3.61),
        ("breakable", "Breakable", 905000, 60.45),
        ("illiquid", "Illiquid", 101000, 6.75),
        # EPF + PPF 300,000 + NPS Tier I 3,000 + the ELSS lot bought 2024-06-10 (4,000).
        ("locked", "Locked", 307000, 20.51),
        ("not_classified", "Not classified", 100000, 6.68),
    ]  # fmt: skip


# --- Coming up ---------------------------------------------------------------------------------


def _row(r):
    return (
        r["type"], r["id"], r["name"], r["maturity_date"], r["amount"], r["rate"], r["days_left"],
        r["approximate"],
    )  # fmt: skip


def test_coming_up_amounts_and_windows(client, seeded):
    coming = _overview(client, seeded[0])["coming_up"]
    in_90 = coming["next_90_days"]
    assert in_90["until"] == "2027-01-31"
    # A payout FD returns its principal; a bond returns face value x quantity (10 x 1,000).
    assert [_row(r) for r in in_90["rows"]] == [
        ("fd", 3, "SURYODAY Small  Finance Bank Limited", "2026-12-02", 200000, 8, 30, False),
        ("bond", 1, "NHAI 2030", "2027-01-15", 10000, 7, 74, False),
    ]
    assert in_90["total"] == 210000

    in_year = coming["next_12_months"]
    assert in_year["until"] == "2027-11-02"
    assert [_row(r) for r in in_year["rows"]] == [
        ("fd", 3, "SURYODAY Small  Finance Bank Limited", "2026-12-02", 200000, 8, 30, False),
        ("bond", 1, "NHAI 2030", "2027-01-15", 10000, 7, 74, False),
        # 5,000 a month on 2 Nov, 2 Dec and 2 Jan at 6% compounded quarterly to 2 Feb:
        # 5000 x (1.015^(4 x 92/365) + 1.015^(4 x 62/365) + 1.015^(4 x 31/365)).
        ("rd", 1, "SBI", "2027-02-02", 15151.81, 6, 92, True),
        # PPF: 200,000 + 200,000 x 7.1% x 150/365 simple interest to 1 Apr 2027.
        ("pf", 2, "PPF", "2027-04-01", 205835.62, 7.1, 150, True),
        # An SGB redeems at the gold price: its value today (31,000), not face value.
        ("bond", 2, "SGB 2027", "2027-06-01", 31000, 2.5, 211, True),
        # Cumulative FD: 300,000 x (1 + 8%/4)^4 = 324,729.648.
        ("fd", 1, "HDFC Bank · Joint", "2027-11-02", 324729.65, 8, 365, False),
        ("fd", 2, "HDFC Ltd", "2027-11-02", 300000, 8, 365, False),
        # 100,000 x 1.02^4 = 108,243.216.
        ("fd", 4, "Local Co-op Bank", "2027-11-02", 108243.22, 8, 365, False),
    ]
    assert in_year["total"] == 1194960.3

    # The matured bond is listed apart and counted in no total or row.
    assert coming["already_matured"] == {
        "count": 1,
        "rows": [{"type": "bond", "id": 3, "name": "Old Bond", "maturity_date": "2026-10-01"}],
    }
    assert "Old Bond" not in {r["name"] for r in in_year["rows"]}


# --- Bank safety -------------------------------------------------------------------------------


def test_bank_safety_rolls_up_merged_and_name_matched_banks(client, seeded):
    safety = _overview(client, seeded[0])["bank_safety"]
    assert (
        safety["limit"], safety["total_deposits"], safety["insured"],
        safety["uninsured_excess"], safety["unknown_amount"], safety["sovereign_amount"],
    ) == (500000, 905000, 705000, 100000, 100000, 0)  # fmt: skip
    banks = safety["banks"]
    assert [
        (b["key"], b["name"], b["issuer_id"], b["category"], b["status"], b["badges"],
         b["total"], b["insured"], b["excess"])
        for b in banks
    ] == [
        # HDFC Bank 300,000 + HDFC Ltd (merged into it) payout principal 300,000 = 600,000.
        ("issuer:1", "HDFC Bank", 1, "private_sector", "insured", [], 600000, 500000, 100000),
        # The manual FD's name equals the issuer name apart from case and a double space.
        ("issuer:3", "Suryoday", 3, "small_finance", "insured", ["small_finance"], 200000, 200000, 0),
        ("name:local co-op bank", "Local Co-op Bank", None, None, "unknown", [], 100000, None, None),
        # The RD's entered bank "SBI" equals the issuer's short name.
        ("issuer:4", "SBI", 4, "public_sector", "insured", [], 5000, 5000, 0),
    ]  # fmt: skip
    assert [(h["type"], h["id"], h["name"], h["amount"]) for h in banks[0]["holdings"]] == [
        ("fd", 1, "HDFC Bank · Joint", 300000),
        ("fd", 2, "HDFC Ltd", 300000),
    ]
    assert [(h["type"], h["id"], h["name"], h["amount"]) for h in banks[3]["holdings"]] == [
        ("rd", 1, "SBI", 5000)
    ]
    assert [
        (h["id"], h["label"], h["rate"], h["maturity_date"], h["payout"])
        for h in banks[0]["holdings"]
    ] == [
        (1, "Joint", 8, "2027-11-02", False),
        (2, None, 8, "2027-11-02", True),
    ]
    (rd,) = banks[3]["holdings"]
    assert (rd["label"], rd["rate"], rd["payout"]) == (None, 6, False)


# --- Data health -------------------------------------------------------------------------------


def test_data_health_flags_holdings_valued_at_cost(client, seeded):
    health = _overview(client, seeded[0])["data_health"]
    # Priced and with a NAV or rate: Reliance, both ETFs, flexi cap, ELSS, NPS E, gold 916.
    assert health["at_cost"] == {
        "count": 4,
        "items": [
            {"type": "stock", "id": 4, "name": "Unpriced Ltd"},
            {"type": "mf", "id": 3, "name": "ICICI Prudential Liquid Fund - Growth"},
            {"type": "nps", "id": 2, "name": "HDFC PENSION FUND SCHEME G - TIER II"},
            {"type": "gold", "id": 2, "name": "Silver digital"},
        ],
    }
    assert health["stale_balances"] == {
        "count": 2,
        "items": [
            {"type": "cash", "id": 2, "name": "Old wallet", "as_of": "2026-03-01"},
            {"type": "other", "id": 2, "name": "Old painting", "as_of": "2025-12-01"},
        ],
    }
    assert health["matured_open"] == {
        "count": 1,
        "items": [{"type": "bond", "id": 3, "name": "Old Bond", "maturity_date": "2026-10-01"}],
    }
    assert health["latest"] == {
        "stock_price": "2026-10-31",
        "mf_nav": "2026-11-01",
        "nps_nav": "2026-10-31",
        "gold_rate": "2026-11-02",
    }


def test_data_health_reads_the_price_fields_of_real_items(client, seeded):
    """The at-cost fields (price, nav, rate_per_gram) and the latest-date fields (price_time,
    nav_date, rate_date) exist on the valued items the route feeds the maths."""
    a, _ = seeded
    items = {
        g["type"]: {i.get("name") or i.get("scheme_name"): i for i in g["items"]}
        for g in client.get("/api/portfolio", headers=a).json()["groups"]
    }
    reliance = items["stock"]["Reliance Industries"]
    assert (reliance["price"], reliance["price_time"][:10]) == (2500, "2026-10-30")
    assert items["stock"]["Unpriced Ltd"]["price"] is None
    flexi = items["mf"]["HDFC Flexi Cap Fund - Growth"]
    assert (flexi["nav"], flexi["nav_date"]) == (50, "2026-11-01")
    assert items["mf"]["ICICI Prudential Liquid Fund - Growth"]["nav"] is None
    nps = next(i for i in items["nps"].values() if i["tier"] == "I")
    assert (nps["nav"], nps["nav_date"]) == (30, "2026-10-31")
    wedding = items["gold"]["Wedding set"]
    assert (wedding["rate_per_gram"], wedding["rate_date"]) == (6000, "2026-11-02")
    assert items["gold"]["Silver digital"]["rate_per_gram"] is None
