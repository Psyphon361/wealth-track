from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.stock_master import (
    build_rows,
    is_grace_row,
    merge_rows,
    parse_bse_bhav,
    parse_equity,
    parse_etf,
    parse_nse_bhav,
    pick_stock_symbol,
)
from tests.market_helpers import TODAY, by_isin, make_sources, read


def test_equity_strips_leading_space_headers_and_skips_bad_rows():
    result = parse_equity(read("nse_equity_sample.csv"))
    assert len(result.rows) == 6
    assert result.skipped == 2  # invalid ISIN + short row
    reliance = by_isin(result.rows)["INE002A01018"]
    assert reliance["kind"] == "stock"
    assert reliance["nse_symbol"] == "RELIANCE"
    assert reliance["nse_series"] == "EQ"  # header " SERIES" had a leading space
    assert reliance["face_value"] == Decimal("10.00")
    assert reliance["name"] == "Reliance Industries Limited"


def test_etf_parser_handles_crlf_and_bad_rows():
    text = read("nse_etf_sample.csv").replace("\n", "\r\n")
    result = parse_etf(text)
    assert result.skipped == 1
    etfs = by_isin(result.rows)
    assert etfs["INF204KB14I2"]["kind"] == "etf"
    assert etfs["INF204KB14I2"]["nse_symbol"] == "NIFTYBEES"
    assert etfs["INF732E01045"]["face_value"] == Decimal("1.25")


def test_nse_bhav_keeps_only_sme_series():
    result = parse_nse_bhav(read("nse_bhav_sample.csv"))
    assert len(result.rows) == 3  # SM/ST only; EQ, N0 and GB rows are ignored
    assert result.skipped == 1  # SME row with an invalid ISIN
    rows = by_isin(result.rows)
    sme = rows["INE1GYP01013"]
    assert (sme["kind"], sme["nse_series"], sme["nse_symbol"]) == ("stock", "SM", "AAKAAR")
    assert rows["INE124401014"]["nse_series"] == "ST"
    assert "IN0020200104" not in rows  # SGB belongs to bond_master
    assert "INE144J01027" not in rows


def test_bse_parser_maps_fields_skips_gsec_and_bad_isin():
    result = parse_bse_bhav(read("bse_bhav_sample.csv").replace("\n", "\r\n"))
    assert len(result.rows) == 7
    assert result.skipped == 1
    rows = by_isin(result.rows)
    abb = rows["INE117A01022"]
    assert (abb["kind"], abb["bse_code"], abb["bse_symbol"], abb["bse_group"]) == (
        "stock", "500002", "ABB", "A",
    )
    assert rows["INF740KA1EU7"]["kind"] == "etf"
    assert "IN0020120062" not in rows  # group G


def test_merge_by_isin_prefers_nse_and_fills_bse_fields():
    nse = parse_equity(read("nse_equity_sample.csv")).rows
    bse = parse_bse_bhav(read("bse_bhav_sample.csv")).rows
    merged = by_isin(
        merge_rows({"equity": nse, "bse": bse}, {"equity": TODAY, "bse": date(2026, 10, 23)})
    )
    reliance = merged["INE002A01018"]
    assert reliance["name"] == "Reliance Industries Limited"  # NSE name wins
    assert reliance["nse_symbol"] == "RELIANCE"
    assert reliance["bse_code"] == "500325"
    assert reliance["bse_group"] == "A"
    assert reliance["last_seen"] == TODAY
    abb = merged["INE117A01022"]  # BSE only
    assert abb["nse_symbol"] is None
    assert abb["last_seen"] == date(2026, 10, 23)
    isins = [r["isin"] for r in merge_rows({"equity": nse, "bse": bse}, {"equity": TODAY, "bse": TODAY})]
    assert len(isins) == len(set(isins))


def test_build_rows_combines_all_sources():
    rows, counts, skipped, extra = build_rows(make_sources(), TODAY)
    merged = by_isin(rows)
    assert counts == {"equity": 6, "etf": 6, "bhav": 3, "bse": 7}
    assert skipped == 2 + 1 + 1 + 1
    assert {r["kind"] for r in rows} == {"stock", "etf"}
    assert merged["INF204KB14I2"]["kind"] == "etf"
    assert merged["INF740KA1EU7"]["bse_code"] == "541097"
    assert "IN0020200104" not in merged
    assert extra["dates"] == {"bhav": date(2026, 10, 23), "bse": date(2026, 10, 23)}
    assert extra["errors"] == {"bhav": None, "bse": None}


def test_bse_row_with_a_debt_isin_is_not_a_stock():
    debt = read("nse_debt_sample.csv")
    bond_isin = "INE674K07150"
    bse = (
        "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,FinInstrmNm\n"
        f"2026-10-23,2026-10-23,CM,BSE,STK,959999,{bond_isin},ABCLBOND,F,SOME BOND\n"
        "2026-10-23,2026-10-23,CM,BSE,STK,500002,INE117A01022,ABB,A,ABB LTD\n"
    )
    rows, counts, _, _ = build_rows(make_sources(debt=debt, bse=(date(2026, 10, 23), bse)), TODAY)
    assert bond_isin not in by_isin(rows)
    assert counts["bse"] == 1


def test_bse_failure_is_reported_and_import_continues():
    rows, counts, _, extra = build_rows(
        make_sources(bse=(date(2026, 10, 23), "<html>blocked</html>")), TODAY
    )
    assert "bse" not in counts
    assert extra["errors"]["bse"] is not None
    assert extra["dates"]["bse"] is None
    assert all(r["bse_code"] is None for r in rows)
    assert len(rows) > 0


def test_bhav_failure_is_reported_and_import_continues():
    rows, counts, _, extra = build_rows(make_sources(bhav=(date(2026, 10, 23), b"not a zip")), TODAY)
    assert "bhav" not in counts
    assert extra["errors"]["bhav"] is not None
    assert len(rows) > 0


def test_missing_optional_sources_carry_their_fetch_errors():
    _, counts, _, extra = build_rows(
        make_sources(bhav=None, bhav_error="LookupError: none", bse=None, bse_error="HTTPError: 403"),
        TODAY,
    )
    assert set(counts) == {"equity", "etf"}
    assert extra["errors"] == {"bhav": "LookupError: none", "bse": "HTTPError: 403"}


def test_empty_required_source_raises():
    with pytest.raises(ValueError, match="etf"):
        build_rows(make_sources(etf="Symbol,SecurityName\n"), TODAY)


@pytest.mark.parametrize(
    ("symbol", "series", "expected"),
    [
        ("RELIANCE", "EQ", False),
        ("NIFTYBEES", "EQ", False),
        ("AAKAAR", "SM", True),
        ("AARADHYA", "ST", True),
        (None, None, True),  # BSE-only
    ],
)
def test_grace_row_predicate(symbol, series, expected):
    assert is_grace_row(symbol, series) is expected


@pytest.mark.parametrize(
    ("nse", "bse", "exchange", "payload", "expected"),
    [
        ("RELIANCE", "RELIANCE", "NSE", "X", "RELIANCE"),
        ("RELIANCE", "RELIND", "BSE", "X", "RELIND"),
        (None, "BSESYM", "NSE", "X", "BSESYM"),
        ("M&M", None, "BSE", "X", "X"),
        ("BAD SYM", "OK1", "NSE", "X", "OK1"),
        ("BAD.SYM", "ALSO.BAD", "NSE", "X", "X"),
        (None, None, "NSE", None, None),
        ("A" * 21, "ABC", "BSE", "X", "ABC"),
    ],
)
def test_pick_stock_symbol(nse, bse, exchange, payload, expected):
    stock = SimpleNamespace(nse_symbol=nse, bse_symbol=bse)
    assert pick_stock_symbol(stock, exchange, payload) == expected
