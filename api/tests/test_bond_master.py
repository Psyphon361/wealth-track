from datetime import date
from decimal import Decimal

import pytest

from app.services.bond_master import (
    build_rows,
    derive_bond_type,
    is_grace_row,
    parse_debt,
    parse_nse_bhav,
)
from tests.market_helpers import TODAY, by_isin, make_sources, read


def test_debt_isin_is_read_by_position_from_headerless_column():
    result = parse_debt(read("nse_debt_sample.csv"))
    assert len(result.rows) == 8
    assert result.skipped == 2
    bonds = by_isin(result.rows)
    abcl = bonds["INE674K07150"]
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


def test_nse_bhav_keeps_only_gold_bond_series():
    result = parse_nse_bhav(read("nse_bhav_sample.csv"))
    assert len(result.rows) == 3  # GB only; SM/ST, EQ and N0 rows are ignored
    assert result.skipped == 0
    rows = by_isin(result.rows)
    sgb = rows["IN0020200104"]
    assert sgb["bond_type"] == "sgb"
    assert sgb["issuer"] == "Government of India"
    assert sgb["coupon_rate"] == Decimal("2.500")
    assert sgb["maturity_date"] is None
    assert "INE1GYP01013" not in rows


def test_build_rows_combines_debt_and_bhav():
    rows, counts, skipped, extra = build_rows(make_sources(), TODAY)
    merged = by_isin(rows)
    assert counts == {"debt": 8, "bhav": 3}
    assert skipped == 2
    assert merged["IN0020200104"]["bond_type"] == "sgb"
    assert all(r["bond_type"] for r in rows)
    assert extra["dates"] == {"bhav": date(2026, 10, 23)}
    assert extra["errors"] == {"bhav": None}


def test_bhav_failure_is_reported_and_import_continues():
    rows, counts, _, extra = build_rows(make_sources(bhav=(date(2026, 10, 23), b"not a zip")), TODAY)
    assert counts == {"debt": 8}
    assert extra["errors"]["bhav"] is not None
    assert len(rows) == 8


def test_missing_bhav_carries_its_fetch_error():
    _, counts, _, extra = build_rows(make_sources(bhav=None, bhav_error="LookupError: none"), TODAY)
    assert set(counts) == {"debt"}
    assert extra["errors"] == {"bhav": "LookupError: none"}


def test_empty_required_source_raises():
    with pytest.raises(ValueError, match="debt"):
        build_rows(make_sources(debt="SYMBOL,NAME OF COMPANY\n"), TODAY)


@pytest.mark.parametrize(
    ("symbol", "series", "expected"),
    [
        ("0ABCL31", "N0", False),
        ("SGBJUN28", "GB", True),
    ],
)
def test_grace_row_predicate(symbol, series, expected):
    assert is_grace_row(symbol, series) is expected
