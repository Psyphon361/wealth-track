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
    MFMaster,
    MFNavHistory,
    MutualFund,
    Nps,
    NpsMaster,
    Other,
    Pf,
    RecurringDeposit,
    Stock,
    StockMaster,
    StockPriceLatest,
)
from app.routers.portfolio import LABELS
from app.services import search_index
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

D = date(2026, 10, 1)
TYPES = ["fd", "rd", "stock", "bond", "mf", "nps", "gold", "cash", "pf", "other"]


def _holdings(user_id: int, tag: str = "") -> list:
    """One holding of every type for a user; `tag` makes another user's titles distinct."""
    return [
        FixedDeposit(
            user_id=user_id, bank="HDFC Bank", label="Retirement", issuer_id=1,
            principal=100000, rate=Decimal("7.25"), start_date=D, compounding="quarterly",
            payout_type="cumulative", tenure_years=1,
        ),
        RecurringDeposit(
            user_id=user_id, bank=f"SBI{tag}", monthly_instalment=5000, rate=Decimal("6.5"),
            start_date=D, compounding="quarterly", tenure_years=1,
        ),
        Stock(
            user_id=user_id, name=f"Reliance Industries{tag}", symbol="RELIANCE", exchange="NSE",
            master_id=1, broker="Zerodha", quantity=10, avg_buy_price=100, buy_date=D,
        ),
        Bond(
            user_id=user_id, name=f"NHAI 2030{tag}", isin="INE906B07EA3", issuer="NHAI",
            bond_type="tax_free", master_id=1, platform="Wint", quantity=1, face_value=1000,
            purchase_price=1000, invested_amount=1000, purchase_date=D, ytm=7,
            maturity_date=date(2030, 1, 1),
        ),
        MutualFund(
            user_id=user_id, scheme_name=f"HDFC Flexi Cap{tag}", scheme_code=120503,
            platform="Groww", category="equity", units=10, avg_nav=100, invested_amount=1000,
            purchase_date=D,
        ),
        Nps(user_id=user_id, scheme_id="SM001003", units=10, contributed=1000, start_date=D),
        Gold(
            user_id=user_id, name=f"Wedding set{tag}", form="jewellery", metal="gold",
            purity="916", weight_grams=10, purchase_date=D, invested_amount=50000,
        ),
        Cash(
            user_id=user_id, name=f"Salary account{tag}", kind="savings", balance=25000,
            balance_date=D,
        ),
        Pf(
            user_id=user_id, name=f"Employer EPF{tag}", kind="epf", balance=100000,
            balance_date=D, interest_rate=Decimal("8.25"),
        ),
        Other(
            user_id=user_id, name=f"Bitcoin{tag}", category="Crypto", current_value=80000,
            value_date=D,
        ),
    ]


@pytest.fixture
def seeded(client, users, auth_engine):  # noqa: F811
    """Masters plus a full set of holdings for user A and a tagged set for user B."""
    a, a_id, b, b_id = users
    # bond_master has a Postgres-only ARRAY column; the search reads just these two columns.
    Base.metadata.create_all(
        auth_engine,
        tables=[
            m.__table__
            for m in (StockMaster, StockPriceLatest, MFMaster, MFNavHistory, FdIssuerMaster)
        ],
    )
    with auth_engine.begin() as conn:
        conn.execute(text("CREATE TABLE bond_master (id INTEGER PRIMARY KEY, nse_symbol VARCHAR)"))
        conn.execute(text("INSERT INTO bond_master (id, nse_symbol) VALUES (1, 'NHAI30')"))
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                StockMaster(
                    id=1, isin="INE002A01018", kind="stock", name="Reliance Industries Ltd",
                    nse_symbol="RELIANCE", bse_symbol="RELIND", bse_code="500325",
                ),
                MFMaster(
                    scheme_code=120503, name="HDFC Flexi Cap Fund - Growth", amc="HDFC Mutual Fund",
                    category="equity", isin_growth_payout="INF179K01VF4",
                    isin_reinvest="INF179K01VG2",
                ),
                FdIssuerMaster(
                    id=1, code="hdfc", name="HDFC Bank Limited", short_name="HDFC Bank Ltd",
                    category="private_sector",
                ),
                NpsMaster(
                    scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                    scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E",
                ),
            ]
        )
        session.flush()
        session.add_all(_holdings(a_id) + _holdings(b_id, " (B)"))
        session.commit()
    return a, a_id, b


def _index(client, headers) -> list[dict]:
    response = client.get("/api/search/index", headers=headers)
    assert response.status_code == 200
    return response.json()["items"]


def _by_type(items: list[dict]) -> dict[str, dict]:
    return {i["type"]: i for i in items}


def test_all_ten_types_with_titles_and_labels(client, seeded):
    a, _, _ = seeded
    items = _index(client, a)
    assert [i["type"] for i in items] == TYPES
    by_type = _by_type(items)
    assert {t: i["type_label"] for t, i in by_type.items()} == LABELS
    assert {t: i["title"] for t, i in by_type.items()} == {
        "fd": "HDFC Bank · Retirement",
        "rd": "SBI",
        "stock": "Reliance Industries",
        "bond": "NHAI 2030",
        "mf": "HDFC Flexi Cap",
        "nps": "SBI PENSION FUND SCHEME E - TIER I",
        "gold": "Wedding set",
        "cash": "Salary account",
        "pf": "Employer EPF",
        "other": "Bitcoin",
    }
    assert all(i["status"] and isinstance(i["current_value"], float) for i in items)
    assert all(datetime.fromisoformat(i["updated_at"]) for i in items)


def test_subtitles(client, seeded):
    by_type = _by_type(_index(client, seeded[0]))
    assert {t: i["subtitle"] for t, i in by_type.items()} == {
        "fd": "7.25% p.a.",
        "rd": "6.5% p.a.",
        "stock": "RELIANCE · NSE · Zerodha",
        "bond": "NHAI · Tax-free",
        "mf": "HDFC Mutual Fund · Equity",
        "nps": "SBI Pension Funds · Tier I",
        "gold": "Gold · Jewellery · 22K (916)",
        "cash": "Savings account",
        "pf": "EPF",
        "other": "Crypto",
    }


def test_master_terms_for_linked_stock_and_mf(client, seeded):
    by_type = _by_type(_index(client, seeded[0]))
    assert by_type["stock"]["terms"] == {
        "ids": ["RELIANCE", "RELIND", "500325", "INE002A01018"],
        "strong": [],
        "weak": ["Zerodha"],
    }
    assert by_type["mf"]["terms"] == {
        "ids": ["120503", "INF179K01VF4", "INF179K01VG2"],
        "strong": ["HDFC Mutual Fund"],
        "weak": ["Groww", "Equity"],
    }


def test_other_master_terms(client, seeded):
    by_type = _by_type(_index(client, seeded[0]))
    # Bank is part of the labelled title, so it is a term; the issuer short name comes on top.
    assert by_type["fd"]["terms"]["strong"] == ["HDFC Bank", "HDFC Bank Ltd"]
    # An unlabelled RD with no issuer link: the bank equals the title, so no term repeats it.
    assert by_type["rd"]["terms"] == {"ids": [], "strong": [], "weak": []}
    assert by_type["bond"]["terms"] == {
        "ids": ["INE906B07EA3", "NHAI30"],
        "strong": ["NHAI"],
        "weak": ["Wint", "Tax-free"],
    }
    assert by_type["nps"]["terms"] == {
        "ids": ["SM001003"],
        "strong": ["SBI Pension Funds"],
        "weak": [],
    }
    assert by_type["gold"]["terms"]["weak"] == ["Gold", "Jewellery", "22K (916)", "916"]


def test_manual_stock_and_mf_without_master_still_appear(client, seeded, auth_engine):
    a, a_id, _ = seeded
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add_all(
            [
                Stock(
                    user_id=a_id, name="Manual Co", exchange="BSE", quantity=1,
                    avg_buy_price=10, buy_date=D,
                ),
                MutualFund(
                    user_id=a_id, scheme_name="Manual Fund", category="debt", units=1,
                    avg_nav=10, invested_amount=10, purchase_date=D,
                ),
                FixedDeposit(
                    user_id=a_id, bank="Local Co-op", principal=1000, rate=7, start_date=D,
                    compounding="quarterly", payout_type="cumulative", tenure_years=1,
                ),
            ]
        )
        session.commit()
    items = {i["title"]: i for i in _index(client, a)}
    assert items["Manual Co"]["subtitle"] == "BSE"
    assert items["Manual Co"]["terms"] == {"ids": [], "strong": [], "weak": []}
    assert items["Manual Fund"]["subtitle"] == "Debt"
    assert items["Manual Fund"]["terms"] == {"ids": [], "strong": [], "weak": ["Debt"]}
    assert items["Local Co-op"]["terms"]["strong"] == []


def test_other_without_invested_has_null_gain(client, seeded):
    by_type = _by_type(_index(client, seeded[0]))
    assert by_type["other"]["gain_pct"] is None
    assert by_type["other"]["current_value"] == 80000
    assert by_type["fd"]["gain_pct"] is not None


def test_other_users_holdings_never_appear(client, seeded):
    a, _, b = seeded
    titles_a = {i["title"] for i in _index(client, a)}
    titles_b = {i["title"] for i in _index(client, b)}
    assert not any("(B)" in t for t in titles_a)
    assert "Bitcoin (B)" in titles_b and "Bitcoin" not in titles_b
    assert len(titles_a) == len(titles_b) == 10


def test_soft_deleted_holding_is_excluded(client, seeded, auth_engine):
    a, a_id, _ = seeded
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            Cash(
                user_id=a_id, name="Gone account", kind="cash", balance=1, balance_date=D,
                deleted_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    assert "Gone account" not in {i["title"] for i in _index(client, a)}


def test_requires_bearer(client):
    assert client.get("/api/search/index").status_code == 401


def test_cache_control_header(client, seeded):
    response = client.get("/api/search/index", headers=seeded[0])
    assert response.headers["cache-control"] == "private, no-store"


def test_build_items_is_pure_and_skips_empty_terms():
    group = {
        "type": "other",
        "label": LABELS["other"],
        "items": [
            {
                "id": 1, "name": "Art", "category": "", "notes": "n", "current_value": 5.0,
                "gain_pct": None, "status": "active", "updated_at": "2026-10-01T00:00:00",
            }
        ],
    }  # fmt: skip
    masters = {"stock": {}, "bond": {}, "mf": {}, "issuer": {}}
    (item,) = search_index.build_items([group], masters)
    assert item["subtitle"] is None
    assert item["terms"] == {"ids": [], "strong": [], "weak": []}
    assert item["notes"] == "n"
