"""on_conflict upserts are idempotent on real Postgres (re-running an import changes nothing).

Every import runs twice with the same in-memory fixtures (no network: the history syncs and the
SIP hook that import_navall calls afterwards are stubbed), then once more with one value
changed. Row counts must not move on the repeat and the changed value must be applied.
"""

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import (
    BondMaster,
    GoldRateHistory,
    GoldRateLatest,
    MFMaster,
    MFNavHistory,
    MFNavHistorySync,
    MFNavLatest,
    MutualFund,
    NpsMaster,
    NpsNavHistory,
    NpsNavHistorySync,
    NpsNavLatest,
    StockMaster,
    StockPriceHistory,
    StockPriceLatest,
)
from app.services import amfi, bond_master, gold_rates, nav_history, nps, stock_master
from tests.market_helpers import TODAY, make_sources, read
from tests.pg.conftest import make_user_token
from tests.test_nps_import import HISTORY as NPS_HISTORY
from tests.test_nps_import import LATEST as NPS_LATEST

pytestmark = pytest.mark.pg

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


@pytest.fixture
def session(pg_app):
    with pg_app.session() as s:
        yield s


# --- AMFI NAVAll -----------------------------------------------------------------------------


@pytest.fixture
def navall(pg_app, session, monkeypatch):
    """The NAVAll sample, a held fund (so the history append runs) and no network hooks."""
    monkeypatch.setattr(amfi.nav_history, "sync_missing_history", lambda s: 0)
    monkeypatch.setattr(amfi.analytics_benchmark, "refresh_benchmark_history", lambda s: False)
    monkeypatch.setattr(amfi.sip, "post_due_safely", lambda s: 0)
    text = (FIXTURES / "navall_sample.txt").read_text(encoding="utf-8")
    # The holding references a scheme the first import creates, so insert the master by hand first.
    session.add(MFMaster(scheme_code=151833, name="placeholder", category="debt"))
    user, _ = make_user_token(session)
    session.add(
        MutualFund(
            user_id=user.id, scheme_name="Held", scheme_code=151833, category="debt",
            units=Decimal("1"), avg_nav=Decimal("1"), invested_amount=Decimal("1"),
            purchase_date=date(2026, 1, 1),
        )
    )  # fmt: skip
    session.commit()
    return text


def test_amfi_import_twice_changes_nothing(session, navall):
    first = amfi.import_navall(session, navall)
    assert first.inserted > 0 and first.updated == 1  # the placeholder master is corrected
    schemes, navs = count(session, MFMaster), count(session, MFNavLatest)
    assert schemes == first.rows and navs == first.navs_upserted
    assert first.history_appended == 1  # only the held scheme gets a history row
    assert count(session, MFNavHistory) == 1

    again = amfi.import_navall(session, navall)
    assert (again.inserted, again.updated, again.deactivated) == (0, 0, 0)
    assert again.unchanged == again.rows and again.navs_upserted == 0
    assert again.history_appended == 0
    assert (count(session, MFMaster), count(session, MFNavLatest)) == (schemes, navs)
    assert count(session, MFNavHistory) == 1


def test_amfi_import_applies_changed_nav_and_name(session, navall):
    amfi.import_navall(session, navall)
    changed = navall.replace("1247.9343;25-Oct-2026", "1250.0000;26-Oct-2026").replace(
        "Bajaj Finserv Liquid Fund;Direct Plan;Growth", "Bajaj Finserv Liquid Fund Renamed;Direct Plan;Growth"
    )
    result = amfi.import_navall(session, changed)
    assert result.navs_upserted == 1 and result.updated == 1 and result.inserted == 0
    session.expire_all()
    nav = session.get(MFNavLatest, 151833)
    assert (nav.nav, nav.nav_date) == (Decimal("1250.0000"), date(2026, 10, 26))
    assert session.get(MFMaster, 151833).name.endswith("Renamed")
    assert count(session, MFNavHistory) == 2  # the new date is appended for the held scheme


def test_amfi_import_deactivates_schemes_missing_from_the_file(session, navall):
    amfi.import_navall(session, navall)
    kept = "\n".join(line for line in navall.splitlines() if not line.startswith("120001;"))
    result = amfi.import_navall(session, kept)
    assert result.deactivated == 1
    session.expire_all()
    assert session.get(MFMaster, 120001).is_active is False
    assert amfi.import_navall(session, kept).deactivated == 0  # already inactive


# --- MF NAV history --------------------------------------------------------------------------


def test_mf_store_history_is_idempotent_and_applies_changes(session):
    session.add(MFMaster(scheme_code=100, name="Fund", category="equity"))
    session.commit()
    rows = nav_history.parse_mfapi(json.loads((FIXTURES / "mfapi_sample.json").read_text()))
    today = date(2026, 10, 24)
    first_fetch = datetime(2026, 10, 24, 6, tzinfo=timezone.utc)

    nav_history.store_history(session, 100, rows, today, first_fetch)
    stored = count(session, MFNavHistory)
    assert stored == len(rows) == 30
    sync = session.get(MFNavHistorySync, 100)
    assert (sync.first_date, sync.last_date) == (rows[-1][0], rows[0][0])

    nav_history.store_history(session, 100, rows, today, first_fetch)
    assert count(session, MFNavHistory) == stored
    assert count(session, MFNavHistorySync) == 1

    changed = [(rows[0][0], Decimal("99.0000")), *rows[1:]]
    later = datetime(2026, 10, 25, 6, tzinfo=timezone.utc)
    nav_history.store_history(session, 100, changed, today, later)
    session.expire_all()
    assert count(session, MFNavHistory) == stored
    assert session.get(MFNavHistory, (100, rows[0][0])).nav == Decimal("99.0000")
    assert session.get(MFNavHistorySync, 100).fetched_at == later


def test_mf_append_today_for_holdings_does_nothing_twice(session):
    session.add(MFMaster(scheme_code=100, name="Fund", category="equity"))
    user, _ = make_user_token(session)
    session.add(
        MutualFund(
            user_id=user.id, scheme_name="Held", scheme_code=100, category="equity",
            units=Decimal("1"), avg_nav=Decimal("1"), invested_amount=Decimal("1"),
            purchase_date=date(2026, 1, 1),
        )
    )  # fmt: skip
    session.commit()
    navs = [(100, date(2026, 10, 30), Decimal("50")), (999, date(2026, 10, 30), Decimal("1"))]
    assert nav_history.append_today_for_holdings(session, navs) == 1  # 999 is not held
    session.commit()
    assert nav_history.append_today_for_holdings(session, navs) == 0
    session.commit()
    assert count(session, MFNavHistory) == 1


# --- gold rates ------------------------------------------------------------------------------


def test_gold_import_twice_is_idempotent_and_newer_rates_win(session):
    parsed = gold_rates.parse_rates((FIXTURES / "ibja_home.html").read_text())
    first = gold_rates.import_rates(session, parsed)
    history, latest = count(session, GoldRateHistory), count(session, GoldRateLatest)
    assert first.rows_upserted > 0 and first.backfill_rows > 0
    assert history >= first.rows_upserted and latest == len(parsed.rates)

    gold_rates.import_rates(session, parsed)
    assert (count(session, GoldRateHistory), count(session, GoldRateLatest)) == (history, latest)

    key = ("gold", "999")
    bumped = replace(parsed, rates={**parsed.rates, key: parsed.rates[key] + 100},
                     history={parsed.rate_date: {**parsed.rates, key: parsed.rates[key] + 100}})  # fmt: skip
    gold_rates.import_rates(session, bumped)  # same date: the stored rate is replaced
    session.expire_all()
    assert (count(session, GoldRateHistory), count(session, GoldRateLatest)) == (history, latest)
    latest_row = session.get(GoldRateLatest, key)
    assert latest_row.rate_per_gram == parsed.rates[key] + 100

    older = replace(
        parsed,
        rate_date=date(2026, 10, 1),
        rates={k: v + 1 for k, v in parsed.rates.items()},
        history={date(2026, 10, 1): {k: v + 1 for k, v in parsed.rates.items()}},
    )
    gold_rates.import_rates(session, older)
    session.expire_all()
    assert session.get(GoldRateLatest, key).rate_per_gram == parsed.rates[key] + 100  # not older
    assert session.get(GoldRateLatest, key).rate_date == parsed.rate_date
    assert count(session, GoldRateLatest) == latest


def test_gold_backfill_rows_never_overwrite_stored_history(session):
    parsed = gold_rates.parse_rates((FIXTURES / "ibja_home.html").read_text())
    day = date(2026, 1, 5)
    first = replace(parsed, backfill={day: {("gold", "999"): Decimal("100.00")}})
    gold_rates.import_rates(session, first)
    second = replace(parsed, backfill={day: {("gold", "999"): Decimal("999.00")}})
    gold_rates.import_rates(session, second)
    session.expire_all()
    stored = session.scalar(
        select(GoldRateHistory.rate_per_gram).where(
            GoldRateHistory.metal == "gold", GoldRateHistory.purity == "999",
            GoldRateHistory.rate_date == day,
        )
    )
    assert stored == Decimal("100.00")


# --- NPS -------------------------------------------------------------------------------------


def test_nps_import_twice_and_changed_nav(session):
    parsed = nps.parse_latest(NPS_LATEST)
    first = nps.import_latest(session, parsed)
    assert first.inserted == 3 and first.navs_upserted == 2
    counts = (count(session, NpsMaster), count(session, NpsNavLatest))
    assert counts == (3, 2)

    again = nps.import_latest(session, parsed)
    assert (again.inserted, again.updated, again.navs_upserted, again.deactivated) == (0, 0, 0, 0)
    assert again.unchanged == 3
    assert (count(session, NpsMaster), count(session, NpsNavLatest)) == counts

    changed = NPS_LATEST.replace("53.6052", "54.0000").replace("SBI PENSION FUND SCHEME E", "SBI PF E")
    result = nps.import_latest(session, nps.parse_latest(changed))
    assert (result.updated, result.navs_upserted, result.inserted) == (1, 1, 0)
    session.expire_all()
    assert session.get(NpsNavLatest, "SM001003").nav == Decimal("54.0000")
    assert session.get(NpsMaster, "SM001003").scheme_name.startswith("SBI PF E")


def test_nps_store_history_is_idempotent(session):
    nps.import_latest(session, nps.parse_latest(NPS_LATEST))
    rows = nps.parse_history(NPS_HISTORY, "SM001003")
    today = date(2026, 10, 31)
    now = datetime(2026, 10, 31, 6, tzinfo=timezone.utc)
    nps.store_history(session, "SM001003", rows, today, now)
    stored = count(session, NpsNavHistory)
    assert stored == len(rows) > 0
    nps.store_history(session, "SM001003", rows, today, now)
    assert (count(session, NpsNavHistory), count(session, NpsNavHistorySync)) == (stored, 1)
    changed = [(rows[0][0], Decimal("77.0000")), *rows[1:]]
    nps.store_history(session, "SM001003", changed, today, now.replace(day=30))
    session.expire_all()
    assert count(session, NpsNavHistory) == stored
    assert session.get(NpsNavHistory, ("SM001003", rows[0][0])).nav == Decimal("77.0000")


# --- stock and bond masters (market_files.upsert_master) -----------------------------------


def test_stock_master_import_twice_and_changed_name(session):
    first = stock_master.import_stocks(session, make_sources(), TODAY)
    assert first.inserted == first.total > 0
    total = count(session, StockMaster)
    prices, history = count(session, StockPriceLatest), count(session, StockPriceHistory)
    assert total == first.total and prices > 0

    again = stock_master.import_stocks(session, make_sources(), TODAY)
    assert (again.inserted, again.updated, again.deactivated) == (0, 0, 0)
    assert again.unchanged == again.total
    assert count(session, StockMaster) == total
    assert (count(session, StockPriceLatest), count(session, StockPriceHistory)) == (prices, history)

    equity = read("nse_equity_sample.csv").replace("20 Microns Limited", "20 Microns Renamed")
    changed = stock_master.import_stocks(session, make_sources(equity=equity), TODAY)
    assert (changed.inserted, changed.updated) == (0, 1)
    session.expire_all()
    assert session.scalar(select(StockMaster.name).where(StockMaster.isin == "INE144J01027")) == (
        "20 Microns Renamed"
    )


def test_bond_master_import_twice_and_changed_row(session):
    first = bond_master.import_bonds(session, make_sources(), TODAY)
    assert first.inserted == first.total > 0
    total = count(session, BondMaster)
    again = bond_master.import_bonds(session, make_sources(), TODAY)
    assert (again.inserted, again.updated, again.deactivated) == (0, 0, 0)
    assert count(session, BondMaster) == total
    sources = session.scalar(select(BondMaster.sources).where(BondMaster.isin == "INE674K07150"))
    assert sources and all(isinstance(tag, str) for tag in sources)

    debt = read("nse_debt_sample.csv").replace("Aditya Birla Capital Limited", "ABC Renamed Limited")
    changed = bond_master.import_bonds(session, make_sources(debt=debt), TODAY)
    assert (changed.inserted, changed.updated) == (0, 1)
    session.expire_all()
    assert "Renamed" in session.scalar(select(BondMaster.name).where(BondMaster.isin == "INE674K07150"))
