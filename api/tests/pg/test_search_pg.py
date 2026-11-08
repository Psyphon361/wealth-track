"""Master searches on real Postgres: similarity() ordering over the trigram-indexed columns.

The searches are substring (ILIKE) matches per word, ordered by trigram similarity of the name
to the query. They are NOT typo-tolerant (no fuzzy match is claimed), so a misspelling returns
nothing; that behaviour is pinned here so a change to fuzzy search is a conscious one.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models import (
    BondMaster,
    FdIssuerMaster,
    MFMaster,
    MFNavLatest,
    NpsMaster,
    NpsNavLatest,
    StockMaster,
)
from tests.pg.conftest import make_user_token

pytestmark = pytest.mark.pg


@pytest.fixture
def api(pg_app):
    with pg_app.session() as session:
        _user, headers = make_user_token(session)
    return pg_app, headers


def search(api, kind: str, q: str, **params) -> list[dict]:
    pg_app, headers = api
    response = pg_app.client.get(f"/api/master/{kind}", params={"q": q, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def seed(pg_app, *rows) -> None:
    with pg_app.session() as session:
        session.add_all(rows)
        session.commit()


# --- stocks --------------------------------------------------------------------------------


@pytest.fixture
def stocks(pg_app):
    def stock(isin, name, symbol, **kw):
        return StockMaster(isin=isin, kind="stock", name=name, nse_symbol=symbol, **kw)

    seed(
        pg_app,
        stock("INE002A01018", "Reliance Industries Limited", "RELIANCE"),
        stock("INE000000001", "Relaxo Footwears Limited", "RELAXO"),
        stock("INE467B01029", "Tata Consultancy Services Limited", "TCS"),
        stock("INE155A01022", "Tata Power", "TATAPOWER"),
        stock("INE009A01021", "Infosys Limited", "INFY", bse_code="500209", bse_symbol="INFY"),
        stock("INE0DEAD0001", "Reliance Retired Limited", "RELDEAD", is_active=False),
    )


def test_stock_search_ranks_the_obvious_match_first(api, stocks):
    names = [r["name"] for r in search(api, "stock", "reliance industries")]
    assert names == ["Reliance Industries Limited"]
    names = [r["name"] for r in search(api, "stock", "reliance")]
    assert names == ["Reliance Industries Limited"]  # the inactive twin is hidden


def test_stock_search_orders_by_similarity(api, stocks):
    names = [r["name"] for r in search(api, "stock", "tata")]
    assert names == ["Tata Power", "Tata Consultancy Services Limited"]  # shorter name is closer


def test_stock_search_finds_by_symbol_isin_and_bse_code(api, stocks):
    assert [r["nse_symbol"] for r in search(api, "stock", "INFY")] == ["INFY"]
    assert [r["nse_symbol"] for r in search(api, "stock", "ine467b")] == ["TCS"]
    assert [r["nse_symbol"] for r in search(api, "stock", "500209")] == ["INFY"]


def test_stock_search_is_not_typo_tolerant_and_short_queries_are_empty(api, stocks):
    assert search(api, "stock", "relience") == []
    assert search(api, "stock", "r") == []
    assert len(search(api, "stock", "limited", limit=2)) == 2  # the limit applies


def test_stock_trigram_index_is_usable_by_the_planner(pg_app, stocks):
    with pg_app.engine.connect() as conn:
        conn.execute(text("SET enable_seqscan = off"))
        plan = "\n".join(
            conn.execute(
                text(
                    "EXPLAIN SELECT id FROM stock_master WHERE name ILIKE '%reli%' "
                    "OR nse_symbol ILIKE '%reli%' OR bse_symbol ILIKE '%reli%' "
                    "OR bse_code ILIKE '%reli%' OR isin ILIKE '%reli%'"
                )
            ).scalars()
        )
    assert "ix_stock_master_search_trgm" in plan


# --- bonds ---------------------------------------------------------------------------------


@pytest.fixture
def bonds(pg_app):
    def bond(isin, name, issuer, **kw):
        return BondMaster(
            isin=isin, name=name, issuer=issuer, bond_type=kw.pop("bond_type", "corporate"),
            sources=["nsdl"], **kw,
        )  # fmt: skip

    seed(
        pg_app,
        bond("INE001A07RB4", "HDFC 7.75% 2030", "HDFC Limited", maturity_date=date(2030, 1, 1)),
        bond("INE0KKK07001", "Muthoot Finance 9.5% 2027", "Muthoot Finance Limited"),
        bond("IN0020230001", "SGB 2.50% 2031", "Government of India", bond_type="sgb"),
        bond("INE0OLD07001", "HDFC Old 2020", "HDFC Limited", is_active=False),
    )


def test_bond_search_ranks_name_match_and_uses_issuer_and_isin(api, bonds):
    assert [r["name"] for r in search(api, "bond", "muthoot")] == ["Muthoot Finance 9.5% 2027"]
    assert [r["name"] for r in search(api, "bond", "hdfc")] == ["HDFC 7.75% 2030"]  # not the inactive
    assert [r["isin"] for r in search(api, "bond", "in0020230001")] == ["IN0020230001"]
    assert [r["isin"] for r in search(api, "bond", "government of india")] == ["IN0020230001"]
    assert search(api, "bond", "muthut") == []  # typo: no fuzzy match


def test_bond_sources_array_round_trips_on_postgres(pg_app, bonds):
    with pg_app.session() as session:
        row = session.query(BondMaster).filter_by(isin="INE001A07RB4").one()
        assert row.sources == ["nsdl"]


# --- mutual funds --------------------------------------------------------------------------


@pytest.fixture
def funds(pg_app):
    def fund(code, name, amc, **kw):
        return MFMaster(
            scheme_code=code, name=name, amc=amc, category="equity", plan="direct", option="growth",
            **kw,
        )  # fmt: skip

    seed(
        pg_app,
        fund(100, "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "PPFAS Mutual Fund"),
        fund(101, "Parag Parikh ELSS Tax Saver Fund - Direct Plan - Growth", "PPFAS Mutual Fund"),
        fund(102, "HDFC Flexi Cap Fund - Direct Plan - Growth", "HDFC Mutual Fund"),
        fund(103, "Parag Parikh Retired Fund - Growth", "PPFAS Mutual Fund", is_active=False),
    )
    seed(pg_app, MFNavLatest(scheme_code=100, nav=Decimal("75.1234"), nav_date=date(2026, 10, 30)))


def test_mf_search_ranks_closest_name_first_and_carries_the_nav(api, funds):
    rows = search(api, "mf", "parag parikh flexi")
    assert [r["scheme_code"] for r in rows] == [100]
    assert rows[0]["nav"] == 75.1234 and rows[0]["nav_date"] == "2026-10-30"
    rows = search(api, "mf", "flexi cap")
    assert [r["scheme_code"] for r in rows] == [102, 100]  # shorter name is the closer match
    assert [r["scheme_code"] for r in search(api, "mf", "parag")] == [100, 101]
    assert search(api, "mf", "paragh pariks") == []  # typo: no fuzzy match


def test_mf_search_matches_amc_and_hides_inactive(api, funds):
    assert {r["scheme_code"] for r in search(api, "mf", "ppfas")} == {100, 101}
    assert 103 not in {r["scheme_code"] for r in search(api, "mf", "retired")}


# --- NPS -----------------------------------------------------------------------------------


@pytest.fixture
def nps_schemes(pg_app):
    def scheme(scheme_id, pfm, name, asset_class):
        return NpsMaster(
            scheme_id=scheme_id, pfm_code=scheme_id[:5], pfm_name=pfm, scheme_name=name,
            tier="I", asset_class=asset_class,
        )  # fmt: skip

    seed(
        pg_app,
        scheme("SM001003", "SBI Pension Funds", "SBI PENSION FUND SCHEME E - TIER I", "E"),
        scheme("SM001004", "SBI Pension Funds", "SBI PENSION FUND SCHEME G - TIER I", "G"),
        scheme("SM002001", "UTI Retirement Solutions", "UTI RETIREMENT SOLUTIONS SCHEME E - TIER I", "E"),
    )
    seed(pg_app, NpsNavLatest(scheme_id="SM001003", nav=Decimal("53.6052"), nav_date=date(2026, 10, 31)))


def test_nps_search_by_scheme_and_pfm_name(api, nps_schemes):
    rows = search(api, "nps", "sbi pension")
    assert {r["scheme_id"] for r in rows} == {"SM001003", "SM001004"}
    by_id = {r["scheme_id"]: r for r in rows}
    assert by_id["SM001003"]["nav"] == 53.6052 and by_id["SM001004"]["nav"] is None
    assert [r["scheme_id"] for r in search(api, "nps", "uti")] == ["SM002001"]
    best = search(api, "nps", "sbi pension fund scheme e - tier i")
    assert best[0]["scheme_id"] == "SM001003"  # the exact name ranks above its G sibling
    assert search(api, "nps", "pensoin") == []  # typo: no fuzzy match


# --- FD / RD issuers -----------------------------------------------------------------------


@pytest.fixture
def issuers(pg_app):
    def issuer(code, name, category, **kw):
        return FdIssuerMaster(code=code, name=name, category=category, sources=["seed"], **kw)

    seed(
        pg_app,
        issuer("HDFC", "HDFC Bank Limited", "private_sector", short_name="HDFC Bank"),
        issuer("SBIN", "State Bank of India", "public_sector", short_name="SBI"),
        issuer("BAJFIN", "Bajaj Finance Limited", "nbfc"),
        issuer("HDFCLTD", "HDFC Credila Financial", "nbfc"),
        issuer("DICGC:X", "Gone Bank", "private_sector", is_active=False),
        issuer("NODEP", "No Deposits Bank", "private_sector", accepts_deposits=False),
    )


def test_issuer_search_orders_by_category_then_similarity(api, issuers):
    assert [r["code"] for r in search(api, "fd-issuer", "hdfc")] == ["HDFC", "HDFCLTD"]
    assert [r["code"] for r in search(api, "fd-issuer", "sbi")] == ["SBIN"]  # short name
    assert [r["code"] for r in search(api, "fd-issuer", "bajaj")] == ["BAJFIN"]
    assert search(api, "fd-issuer", "gone") == []  # inactive DICGC-only rows are hidden
    assert search(api, "fd-issuer", "no deposits") == []
    assert search(api, "fd-issuer", "bajej") == []  # typo: no fuzzy match


def test_issuer_sources_array_round_trips_on_postgres(pg_app, issuers):
    with pg_app.session() as session:
        assert session.query(FdIssuerMaster).filter_by(code="HDFC").one().sources == ["seed"]
