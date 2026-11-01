from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from app.services.gold_rates import (
    GoldRatesError,
    ParsedRates,
    _scaled,
    _stored_key,
    import_rates,
    parse_rates,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ibja_home.html"


def test_parse_fixture_latest_pm_rates_per_gram():
    parsed = parse_rates(FIXTURE.read_text())
    assert parsed.rate_date == date(2026, 10, 30)
    assert parsed.session == "PM"
    assert parsed.rates == {
        ("gold", "999"): Decimal("14005.40"),
        ("gold", "995"): Decimal("13949.30"),
        ("gold", "916"): Decimal("12828.90"),
        ("gold", "750"): Decimal("10504.10"),
        ("gold", "585"): Decimal("8193.20"),
        ("silver", "999"): Decimal("181.34"),
    }


def test_parse_silver_per_kg_divided_to_per_gram_for_each_date():
    parsed = parse_rates(FIXTURE.read_text())
    assert parsed.history[date(2026, 10, 30)][("silver", "999")] == Decimal("181.34")
    assert parsed.history[date(2026, 10, 27)][("silver", "999")] == Decimal("192.50")  # PM 192499/kg


def test_parse_page_without_silver_still_parses_gold():
    html = FIXTURE.read_text().replace('data-label="Silver 999"', 'data-label="Silver 000"')
    parsed = parse_rates(html)
    assert ("silver", "999") not in parsed.rates
    assert parsed.rates[("gold", "999")] == Decimal("14005.40")


def test_silver_925_derived_from_999():
    assert _stored_key("silver", "925") == ("silver", "999")
    assert _stored_key("gold", "999") == ("gold", "999")
    assert _scaled("silver", "925", Decimal("192.50")) == Decimal("178.24")
    assert _scaled("silver", "999", Decimal("192.50")) == Decimal("192.50")


def test_parse_fixture_history_has_every_listed_date_with_pm_over_am():
    parsed = parse_rates(FIXTURE.read_text())
    assert sorted(parsed.history) == [
        date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30),
    ]  # fmt: skip
    assert parsed.history[date(2026, 10, 30)][("gold", "999")] == Decimal("14005.40")


def test_parse_missing_purity_raises():
    html = FIXTURE.read_text().replace('data-label="Gold 585"', 'data-label="Gold 000"')
    with pytest.raises(GoldRatesError, match="585"):
        parse_rates(html)


def test_parse_unrecognised_page_raises():
    with pytest.raises(GoldRatesError):
        parse_rates("<html><body>nothing here</body></html>")


class _RecordingSession:
    def __init__(self):
        self.statements = []
        self.committed = False

    def execute(self, statement):
        self.statements.append(statement)

    def commit(self):
        self.committed = True


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def _parsed(day: date, rate: str) -> ParsedRates:
    rates = {("gold", p): Decimal(rate) for p in ("999", "995", "916", "750", "585")}
    rates[("silver", "999")] = Decimal(rate)
    return ParsedRates(day, "PM", rates, {day: rates})


def test_import_latest_only_replaced_when_date_not_older():
    session = _RecordingSession()
    result = import_rates(session, _parsed(date(2026, 10, 1), "100"))
    history_sql, latest_sql = (_sql(s) for s in session.statements)
    assert "ON CONFLICT (metal, purity) DO UPDATE" in latest_sql
    assert "gold_rate_latest.rate_date <= excluded.rate_date" in latest_sql
    assert session.committed
    assert result.rows_upserted == 6
    assert result.rate_date == date(2026, 10, 1)


def test_import_history_upserts_per_purity_and_date():
    session = _RecordingSession()
    import_rates(session, _parsed(date(2026, 10, 1), "100"))
    history_sql = _sql(session.statements[0])
    assert "ON CONFLICT (metal, purity, rate_date) DO UPDATE SET rate_per_gram" in history_sql
