from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import gold_history
from app.services.gold_history import (
    GoldHistoryError,
    backfill_pdf,
    backfill_wayback,
    derive_gold_purities,
    fetch_report,
    parse_report_text,
    parse_wayback,
    pdf_url_candidates,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = (FIXTURES / "ibja_report_2023_02_01.txt").read_text()  # file of 1 Feb, rates of 31 Jan
TYPOS = (FIXTURES / "ibja_report_2022_07_13_typos.txt").read_text()
ASOF_TYPO = (FIXTURES / "ibja_report_2024_01_29_asof_typo.txt").read_text()
WAYBACK = (FIXTURES / "ibja_wayback_sample.html").read_text()


def test_report_is_keyed_by_the_printed_rate_date_not_the_file_date():
    report = parse_report_text(REPORT)
    assert report.rate_date == date(2023, 1, 31)  # the report is dated 1 Feb


def test_report_pm_wins_over_am_and_rates_are_per_gram():
    full = parse_report_text(REPORT).full
    assert full[("gold", "999")] == Decimal("5686.50")  # PM 56865, not AM 57041
    assert full[("gold", "585")] == Decimal("3326.60")
    assert full[("silver", "999")] == Decimal("67.67")  # 67671 per kg
    assert set(full) == {("gold", p) for p in ("999", "995", "916", "750", "585")} | {("silver", "999")}


def test_report_am_used_when_pm_is_zero():
    text = REPORT.replace("Gold 916 52250 52088", "Gold 916 52250 0")
    assert parse_report_text(text).full[("gold", "916")] == Decimal("5225.00")


def test_report_five_day_table():
    spot = parse_report_text(REPORT).spot
    assert sorted(spot) == [date(2023, 1, 25), date(2023, 1, 27), date(2023, 1, 30), date(2023, 1, 31)]
    assert spot[date(2023, 1, 30)] == {("gold", "999"): Decimal("5707.90"), ("silver", "999"): Decimal("68.15")}


def test_report_without_all_gold_purities_has_no_full_row():
    text = REPORT.replace("Gold 585 33369 33266\n", "")
    report = parse_report_text(text)
    assert report.full == {}
    assert report.rate_date == date(2023, 1, 31)


def test_report_without_a_rate_date_is_an_error():
    with pytest.raises(GoldHistoryError):
        parse_report_text("Gold 999 1 2")


def test_report_typo_in_a_purity_is_replaced_by_the_derived_rate():
    report = parse_report_text(TYPOS)
    assert report.full[("gold", "995")] == Decimal("5067.40")  # PDF says 506743


def test_report_typo_dates_are_not_trusted():
    # The spot table says "June" on a July report; the "as of" line is used and the table dropped.
    report = parse_report_text(TYPOS)
    assert report.rate_date == date(2022, 7, 12)
    assert report.spot == {}
    # "as of 25th January 2023" on a January 2024 report: the spot table's top row wins.
    assert parse_report_text(ASOF_TYPO).rate_date == date(2024, 1, 25)


def test_report_ordinal_suffix_split_across_lines():
    text = REPORT.replace("27th January 2023", "27\nth January 2023").replace("25th January", "25\r\nth January")
    assert sorted(parse_report_text(text).spot) == [
        date(2023, 1, 25), date(2023, 1, 27), date(2023, 1, 30), date(2023, 1, 31)
    ]


def test_wayback_parse_pm_over_am_and_skips_blank_days():
    days = parse_wayback(WAYBACK)
    assert sorted(days) == [date(2014, 1, 1), date(2014, 1, 2), date(2014, 1, 3), date(2017, 1, 17)]
    assert days[date(2014, 1, 1)] == {("gold", "999"): Decimal("2929.00"), ("silver", "999"): Decimal("44.14")}
    # No PM published: AM is used.
    assert days[date(2017, 1, 17)][("gold", "999")] == Decimal("2934.50")


def test_derive_gold_purities_from_999():
    derived = derive_gold_purities({("gold", "999"): Decimal("2929.00"), ("silver", "999"): Decimal("44.14")})
    assert derived[("gold", "995")] == Decimal("2917.30")
    assert derived[("gold", "916")] == Decimal("2683.00")
    assert derived[("gold", "750")] == Decimal("2196.80")
    assert derived[("gold", "585")] == Decimal("1713.50")
    assert derived[("silver", "999")] == Decimal("44.14")
    assert derive_gold_purities({("silver", "999"): Decimal("44.14")}) == {("silver", "999"): Decimal("44.14")}


def test_url_candidates_are_ordered_and_encoded():
    urls = pdf_url_candidates(date(2023, 8, 10))
    assert urls[0] == "https://ibja.co/Upload/IBJA_Bullion%20Daily%20Report%20-%2010-08-2023.pdf"
    assert urls[1] == "https://ibja.co/Upload/IBJA_Bullion%20Daily%20Report%20-10-08-2023.pdf"
    assert urls[2] == "https://ibja.co/Upload/IBJA_Bullion%20Daily%20Report%2010-08-2023.pdf"
    assert urls[3].endswith("10-08-2023%20.pdf")  # trailing space before .pdf
    assert len(urls) == len(set(urls)) == 4


def test_fetch_report_tries_variants_in_order_and_stops_at_the_first_pdf():
    wanted = pdf_url_candidates(date(2024, 5, 2))[2]
    calls: list[str] = []

    def fake(url: str) -> bytes | None:
        calls.append(url)
        return b"%PDF-1.7 data" if url == wanted else None

    assert fetch_report(date(2024, 5, 2), fake, lambda s: None) == b"%PDF-1.7 data"
    assert calls == pdf_url_candidates(date(2024, 5, 2))[:3]


def test_fetch_report_gives_up_after_all_variants_and_ignores_non_pdf_bodies():
    calls: list[str] = []

    def fake(url: str) -> bytes | None:
        calls.append(url)
        return b"<html>not found page</html>"

    assert fetch_report(date(2024, 5, 2), fake, lambda s: None) is None
    assert calls == pdf_url_candidates(date(2024, 5, 2))


def _pdf_fetcher(available: dict[date, str], monkeypatch: pytest.MonkeyPatch):
    """A fetcher serving fake PDFs (named for the date) and a pdf_text that returns their text."""
    by_url = {pdf_url_candidates(d)[0]: text for d, text in available.items()}
    monkeypatch.setattr(gold_history, "pdf_text", lambda data: data.decode().removeprefix("%PDF"))

    def fetch(url: str) -> bytes | None:
        text = by_url.get(url)
        return None if text is None else b"%PDF" + text.encode()

    return fetch


def test_backfill_pdf_fills_missing_dates_from_the_five_day_table(monkeypatch, capsys):
    fetch = _pdf_fetcher({date(2023, 2, 1): REPORT}, monkeypatch)
    stats = backfill_pdf(
        None, date(2023, 1, 25), date(2023, 1, 31), dry_run=True, fetch=fetch,
        pause=lambda s: None, today=date(2023, 2, 1),
    )
    assert stats.found_full == {date(2023, 1, 31)}
    # Only gold 999 and silver 999 are filled, and only for dates without a full row.
    assert stats.found_filled == {date(2023, 1, 25), date(2023, 1, 27), date(2023, 1, 30)}
    assert stats.missing == [date(2023, 1, 25), date(2023, 1, 26), date(2023, 1, 27), date(2023, 1, 30), date(2023, 1, 31)]
    assert stats.inserted == 0
    out = capsys.readouterr().out
    assert "[pdf] 2023-01-31" in out and "gold 999=56865/10g" in out
    assert "[pdf 5-day-table] 2023-01-30" in out


def test_backfill_pdf_full_row_beats_the_five_day_table(monkeypatch):
    # The 1 Feb report has a full row for 31 Jan; a later report lists 31 Jan in its own table.
    later = REPORT.replace("01st February 2023", "02nd February 2023").replace("31st January 2023 56865", "31st January 2023 11111", 1)
    fetch = _pdf_fetcher({date(2023, 2, 1): REPORT, date(2023, 2, 2): later}, monkeypatch)
    stats = backfill_pdf(
        None, date(2023, 1, 31), date(2023, 1, 31), dry_run=True, fetch=fetch,
        pause=lambda s: None, today=date(2023, 2, 2),
    )
    assert stats.found_full == {date(2023, 1, 31)}
    assert stats.found_filled == set()


def test_backfill_wayback_filters_range_and_derives_purities(capsys):
    stats = backfill_wayback(None, date(2014, 1, 1), date(2014, 1, 2), dry_run=True, fetch=lambda url: WAYBACK.encode())
    assert stats.found_full == {date(2014, 1, 1), date(2014, 1, 2)}
    out = capsys.readouterr().out
    assert "gold 999=29290/10g" in out and "silver 999=44140/kg" in out
    assert "gold 585=17135/10g" in out
    assert "2017-01-17" not in out


def test_backfill_wayback_999_only_without_ratios(capsys):
    backfill_wayback(None, date(2014, 1, 1), date(2014, 1, 1), dry_run=True, fetch=lambda url: WAYBACK.encode(), ratios={})
    out = capsys.readouterr().out
    assert "gold 999" in out and "gold 585" not in out
