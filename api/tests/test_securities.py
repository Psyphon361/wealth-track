import io
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.securities import (
    Sources,
    build_rows,
    derive_bond_type,
    is_grace_row,
    is_html,
    merge_rows,
    parse_bse_bhav,
    parse_debt,
    parse_equity,
    parse_etf,
    parse_nse_bhav,
)

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 10, 26)


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def by_isin(rows):
    return {r["isin"]: r for r in rows}


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


def test_debt_isin_is_read_by_position_from_headerless_column():
    result = parse_debt(read("nse_debt_sample.csv"))
    assert len(result.rows) == 8
    assert result.skipped == 2
    bonds = by_isin(result.rows)
    abcl = bonds["INE674K07150"]
    assert abcl["kind"] == "bond"
    assert abcl["issuer"] == "Aditya Birla Capital Limited"
    assert abcl["maturity_date"] == date(2031, 6, 25)
    assert abcl["face_value"] == Decimal("100000.00")
    assert abcl["coupon_rate"] == Decimal("0.000")
    assert abcl["name"] == "Aditya Birla Capital Limited 25 Jun 2031 (0ABCL31)"
    scl = bonds["INE148I07UR1"]
    assert scl["coupon_rate"] == Decimal("10.030")
    assert scl["name"] == "Sammaan Capital Limited 10.03% 25 Sep 2031 (1003SCL31A)"
    assert bonds["IN002026Y261"]["coupon_rate"] is None


@pytest.mark.parametrize(
    ("series", "symbol", "name", "issuer", "expected"),
    [
        ("GS", "574GS2026", "x", "Government of India", "government"),
        ("TB", "182D010427", "x", "Government of India", "government"),
        ("SG", "582RJ27", "x", "Rajasthan State", "government"),
        ("GB", "SGBJUN28", "x", "Government of India", "sgb"),
        ("N2", "738REC27TF", "REC Limited 7.38%", "REC Limited", "tax_free"),
        ("N1", "X1", "NHAI Tax Free Bonds", "NHAI", "tax_free"),
        ("N1", "X2", "Foo Taxfree Series", "Foo", "tax_free"),
        ("N1", "X3", "Foo TF Series", "Foo", "tax_free"),
        ("N0", "708TFSIL27", "Toyota Financial Services India Limited", "Toyota Financial Services India Limited", "corporate"),
        ("N0", "70826LTF28", "L&T Finance Limited", "L&T Finance Limited", "corporate"),
        ("N0", "0ABCL31", "Aditya Birla Capital Limited", "Aditya Birla Capital Limited", "corporate"),
    ],
)
def test_bond_type_derivation(series, symbol, name, issuer, expected):
    assert derive_bond_type(series, symbol, name, issuer) == expected


def test_debt_rows_carry_derived_bond_type():
    bonds = by_isin(parse_debt(read("nse_debt_sample.csv")).rows)
    assert bonds["IN0020210186"]["bond_type"] == "government"
    assert bonds["IN2920200556"]["bond_type"] == "government"
    assert bonds["IN002026Y261"]["bond_type"] == "government"
    assert bonds["INE020B07GX4"]["bond_type"] == "tax_free"
    assert bonds["INE692Q07621"]["bond_type"] == "corporate"
    assert bonds["INE674K07150"]["bond_type"] == "corporate"


def test_nse_bhav_keeps_only_sme_and_gold_bond_series():
    result = parse_nse_bhav(read("nse_bhav_sample.csv"))
    assert len(result.rows) == 6  # 3 SM/ST + 3 GB; EQ and N0 rows are ignored
    assert result.skipped == 1  # SME row with an invalid ISIN
    rows = by_isin(result.rows)
    sme = rows["INE1GYP01013"]
    assert (sme["kind"], sme["nse_series"], sme["nse_symbol"]) == ("stock", "SM", "AAKAAR")
    assert rows["INE124401014"]["nse_series"] == "ST"
    sgb = rows["IN0020200104"]
    assert sgb["kind"] == "bond"
    assert sgb["bond_type"] == "sgb"
    assert sgb["issuer"] == "Government of India"
    assert sgb["coupon_rate"] == Decimal("2.500")
    assert sgb["maturity_date"] is None
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


def _zip(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BhavCopy.csv", text)
    return buffer.getvalue()


def _sources(**overrides) -> Sources:
    base = {
        "equity": read("nse_equity_sample.csv"),
        "etf": read("nse_etf_sample.csv"),
        "debt": read("nse_debt_sample.csv"),
        "bhav": (date(2026, 10, 23), _zip(read("nse_bhav_sample.csv"))),
        "bse": (date(2026, 10, 23), read("bse_bhav_sample.csv")),
    }
    return Sources(**{**base, **overrides})


def test_build_rows_combines_all_sources():
    rows, counts, skipped, extra = build_rows(_sources(), TODAY)
    merged = by_isin(rows)
    assert counts == {"equity": 6, "etf": 6, "debt": 8, "bhav": 6, "bse": 7}
    assert skipped == 2 + 1 + 2 + 1 + 1
    assert {r["kind"] for r in rows} == {"stock", "etf", "bond"}
    assert merged["INF204KB14I2"]["kind"] == "etf"
    assert merged["INF740KA1EU7"]["bse_code"] == "541097"
    assert merged["IN0020200104"]["bond_type"] == "sgb"
    assert extra["dates"] == {"bhav": date(2026, 10, 23), "bse": date(2026, 10, 23)}
    assert extra["errors"] == {"bhav": None, "bse": None}


def test_bse_failure_is_reported_and_import_continues():
    rows, counts, _, extra = build_rows(_sources(bse=(date(2026, 10, 23), "<html>blocked</html>")), TODAY)
    assert "bse" not in counts
    assert extra["errors"]["bse"] is not None
    assert extra["dates"]["bse"] is None
    assert all(r["bse_code"] is None for r in rows)
    assert len(rows) > 0


def test_missing_optional_sources_carry_their_fetch_errors():
    _, counts, _, extra = build_rows(
        _sources(bhav=None, bhav_error="LookupError: none", bse=None, bse_error="HTTPError: 403"),
        TODAY,
    )
    assert set(counts) == {"equity", "etf", "debt"}
    assert extra["errors"] == {"bhav": "LookupError: none", "bse": "HTTPError: 403"}


def test_empty_required_source_raises():
    with pytest.raises(ValueError, match="debt"):
        build_rows(_sources(debt="SYMBOL,NAME OF COMPANY\n"), TODAY)


@pytest.mark.parametrize(
    ("symbol", "series", "expected"),
    [
        ("RELIANCE", "EQ", False),
        ("NIFTYBEES", "EQ", False),
        ("0ABCL31", "N0", False),
        ("AAKAAR", "SM", True),
        ("AARADHYA", "ST", True),
        ("SGBJUN28", "GB", True),
        (None, None, True),  # BSE-only
    ],
)
def test_grace_row_predicate(symbol, series, expected):
    assert is_grace_row(symbol, series) is expected


def test_html_shell_is_detected_as_missing_file():
    assert is_html(b"<!DOCTYPE html><html>")
    assert is_html(b"  \n<HTML><HEAD>")
    assert not is_html(b"TradDt,BizDt,Sgmt")
    assert not is_html(_zip("a,b\n1,2\n"))


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
    from types import SimpleNamespace

    from app.services.securities import pick_stock_symbol

    security = SimpleNamespace(nse_symbol=nse, bse_symbol=bse)
    assert pick_stock_symbol(security, exchange, payload) == expected
