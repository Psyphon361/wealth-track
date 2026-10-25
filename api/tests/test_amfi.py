from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.amfi import (
    idcw_frequency,
    infer_option_from_name,
    map_category,
    normalise_option,
    parse_navall,
)

SAMPLE = (Path(__file__).parent / "fixtures" / "navall_sample.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rows():
    return {r.scheme_code: r for r in parse_navall(SAMPLE).rows}


def test_file_date_and_row_count():
    result = parse_navall(SAMPLE)
    assert result.file_date == date(2026, 10, 25)
    assert len(result.rows) == 21
    assert result.skipped == 0


def test_crlf_input_parses_the_same():
    crlf = SAMPLE.replace("\n", "\r\n")
    assert parse_navall(crlf).rows == parse_navall(SAMPLE).rows


def test_header_parsing_category_and_amc(rows):
    liquid = rows[151833]
    assert liquid.amc == "Bajaj Finserv Mutual Fund"
    assert liquid.amfi_category == "Debt Scheme - Liquid Fund"
    assert rows[122639].amc == "Parag Parikh Mutual Fund"
    assert rows[122639].amfi_category == "Equity Schemes - Flexi Cap Fund"
    assert rows[141950].amfi_category == "Close Ended - ELSS"
    assert rows[106290].amfi_category == "Interval - Income"
    assert rows[106290].amc == "ICICI Prudential Mutual Fund"


def test_row_fields(rows):
    row = rows[151835]
    assert row.name == "Bajaj Finserv Liquid Fund"
    assert row.isin_growth_payout is None
    assert row.isin_reinvest == "INF0QA701029"
    assert not hasattr(row, "nav") and not hasattr(row, "nav_date")


def test_nav_output_is_split_from_master_rows():
    result = parse_navall(SAMPLE)
    navs = {n.scheme_code: n for n in result.navs}
    assert set(navs) == {r.scheme_code for r in result.rows}
    assert navs[151835].nav == Decimal("1034.6939")
    assert navs[151835].nav_date == date(2026, 10, 25)
    assert navs[140002].nav == Decimal("150.5000")
    assert navs[106290].nav_date == date(2017, 9, 26)


@pytest.mark.parametrize(
    ("code", "plan", "option", "frequency"),
    [
        (151835, "direct", "idcw", "daily"),
        (151838, "direct", "idcw", None),  # fortnightly is not tracked
        (151833, "direct", "growth", None),
        (120001, "regular", "growth", None),  # "Growth Option"
        (119544, "direct", "growth", None),  # "GROWTH"
        (119543, "direct", "idcw", None),
        (153964, "direct", "idcw", "monthly"),  # "Monthly IDCW Payout"
        (140002, "regular", "idcw", None),  # "IDCW (Income Distribution CUM Capital Withdrawal)"
        (120697, "direct", "idcw", "monthly"),
        (120698, "regular", "idcw", "quarterly"),  # "QUARTERLY IDCW Option"
        (120699, "regular", "idcw", "half_yearly"),
        (120700, "regular", "idcw", "annual"),
        (120701, "regular", "idcw", "weekly"),
        (141951, "direct", "bonus", None),
    ],
)
def test_plan_and_option_normalisation(rows, code, plan, option, frequency):
    row = rows[code]
    assert (row.plan, row.option, row.idcw_frequency) == (plan, option, frequency)


def test_blank_plan_and_option_are_inferred_from_name(rows):
    inferred = rows[138334]  # "PGIM India Corporate Bond Fund - Direct Plan - Growth"
    assert (inferred.plan, inferred.option) == ("direct", "growth")
    nothing = rows[130947]  # name carries no plan/option
    assert (nothing.plan, nothing.option, nothing.idcw_frequency) == (None, None, None)


def test_name_inference_does_not_mistake_growth_fund_for_growth_option():
    assert infer_option_from_name("ICICI Prudential Growth Fund - Series 4") == (None, None)
    assert infer_option_from_name("Some Fund - Monthly Dividend") == ("idcw", "monthly")
    assert infer_option_from_name("Some Fund (Growth)") == ("growth", None)


def test_option_and_frequency_helpers():
    assert normalise_option("Cumulative") == ("growth", None)
    assert normalise_option("Payout/Reinvestment") == ("other", None)
    assert normalise_option("Half yearly IDCW") == ("idcw", "half_yearly")
    assert idcw_frequency("Yearly IDCW") == "annual"
    assert idcw_frequency("IDCW") is None


@pytest.mark.parametrize(
    ("amfi_category", "expected"),
    [
        ("Equity Scheme - ELSS", "elss"),
        ("Equity Schemes - ELSS- Tax Saver Fund", "elss"),
        ("Close Ended - ELSS", "elss"),
        ("Equity Scheme - Contra Fund", "equity"),
        ("Equity Schemes - Flexi Cap Fund", "equity"),
        ("Debt Scheme - Liquid Fund", "liquid"),
        ("Debt Scheme - Overnight Fund", "liquid"),
        ("Debt Scheme - Money Market Fund", "liquid"),
        ("Income/Debt Oriented Schemes - Liquid Fund", "liquid"),
        ("Debt Scheme - Corporate Bond Fund", "debt"),
        ("Income/Debt Oriented Schemes - Ultra Short Term Fund", "debt"),
        ("Hybrid Scheme - Aggressive Hybrid Fund", "hybrid"),
        ("Hybrid Schemes - Balanced Hybrid Fund", "hybrid"),
        ("Other Scheme - Index Funds", "index"),
        ("Index Funds - Equity Funds", "index"),
        ("Exchange Traded Funds (ETFs) - Other ETF", "index"),
        ("Other Scheme - FoF Overseas", "other"),
        ("Solution Oriented Scheme - Children’s Fund", "other"),
        ("Close Ended - Growth", "other"),
        ("Interval - Income", "other"),
        (None, "other"),
    ],
)
def test_category_mapping(amfi_category, expected):
    assert map_category(amfi_category) == expected


def test_categories_on_sample(rows):
    assert rows[151833].category == "liquid"
    assert rows[120001].category == "liquid"
    assert rows[119544].category == "elss"
    assert rows[122639].category == "equity"
    assert rows[140001].category == "index"
    assert rows[120697].category == "debt"
    assert rows[141950].category == "elss"
    assert rows[106290].category == "other"


def test_stale_rows_are_inactive(rows):
    assert rows[130947].is_active is False  # 2020
    assert rows[138334].is_active is False  # 2019
    assert rows[106290].is_active is False  # 2017
    assert rows[122639].is_active is True
    assert rows[151833].is_active is True


def test_stale_cutoff_is_thirty_days_before_file_max():
    text = (
        "A Mutual Fund\n"
        "1;-;-;Fund One;Direct Plan;Growth;10;25-Oct-2026\n"
        "2;-;-;Fund Two;Direct Plan;Growth;10;25-Sep-2026\n"
        "3;-;-;Fund Three;Direct Plan;Growth;10;24-Sep-2026\n"
    )
    active = {r.scheme_code: r.is_active for r in parse_navall(text).rows}
    assert active == {1: True, 2: True, 3: False}


def test_malformed_lines_are_skipped_not_fatal():
    text = (
        "Open Ended Schemes(Equity Scheme - Large Cap Fund)\n"
        "Some Mutual Fund\n"
        "not-a-code;a;b;Broken;Direct Plan;Growth;1;25-Oct-2026\n"
        "too;few;fields\n"
        "7;-;-;;Direct Plan;Growth;1;25-Oct-2026\n"
        "8;-;-;Bad Nav Fund;Direct Plan;Growth;N.A.;25-Oct-2026\n"
        "9;-;-;Bad Date Fund;Direct Plan;Growth;1;32-Foo-2026\n"
        "10;-;-;Good Fund;Direct Plan;Growth;12.34567;25-Oct-2026\n"
    )
    result = parse_navall(text)
    by_code = {r.scheme_code: r for r in result.rows}
    navs = {n.scheme_code: n for n in result.navs}
    assert result.skipped == 3
    assert set(by_code) == {8, 9, 10}
    assert set(navs) == {10}  # no NAV row without a valid NAV and date
    assert by_code[9].is_active is False
    assert navs[10].nav == Decimal("12.3457")
    assert by_code[10].category == "equity"


def test_empty_input():
    result = parse_navall("")
    assert result.rows == [] and result.file_date is None
