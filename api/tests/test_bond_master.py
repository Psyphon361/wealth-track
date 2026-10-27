from datetime import date
from decimal import Decimal

import pytest

from app.services.bond_master import (
    _row,
    bond_display_name,
    build_rows,
    derive_bond_type,
    is_grace_row,
    is_social_exchange,
    merge_rows,
    parse_debt,
    parse_nse_bhav,
    parse_nse_ratings,
    parse_nse_sgb,
    parse_seed_sgb,
    parse_seed_tax_free,
    tax_free_display_name,
)
from app.services.market_files import merged_tags_sql
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


# --- Enrichment ------------------------------------------------------------------


def _all_sources(**overrides):
    return make_sources(
        nse_sgb=read("nse_sgb_sample.json"),
        nse_ratings=read("nse_ratings_sample.json"),
        seed_sgb=read("seed_sgb_sample.csv"),
        seed_tax_free=read("seed_tax_free_sample.csv"),
        **overrides,
    )


def test_government_names_are_readable():
    bonds = by_isin(parse_debt(read("nse_debt_sample.csv")).rows)
    assert bonds["IN0020210186"]["name"] == "5.74% GOI 2026"
    assert bonds["IN002026Y261"]["name"] == "T-Bill 01 Apr 2027"
    assert bonds["IN2920200556"]["name"] == "5.82% Rajasthan SDL 2027"


@pytest.mark.parametrize(
    ("issuer", "expected"),
    [
        ("Chattisgarh State", "5.88% Chhattisgarh SDL 2026"),
        ("Puducherry - Union Territory", "5.88% Puducherry SDL 2026"),
        ("Jammu & Kashmir State", "5.88% Jammu & Kashmir SDL 2026"),
        ("Tamilnadu State", "5.88% Tamil Nadu SDL 2026"),
    ],
)
def test_state_names_in_sdl_titles(issuer, expected):
    assert bond_display_name("SG", issuer, Decimal("5.880"), date(2026, 12, 30), "X") == expected


def test_government_name_without_coupon_or_maturity():
    assert bond_display_name("GS", "Government of India", None, date(2033, 1, 1), "X") == "GOI 2033"
    assert bond_display_name("GS", "Government of India", Decimal("7.18"), None, "S1") == (
        "Government of India 7.18% (S1)"
    )
    assert bond_display_name("N0", "Foo Limited", Decimal("8"), date(2030, 1, 5), "F30") == (
        "Foo Limited 8% 05 Jan 2030 (F30)"
    )


def test_social_stock_exchange_rows_are_excluded():
    header = "SYMBOL, NAME OF COMPANY, SERIES, FACE VALUE, PAID UP VALUE, MKT LOT, IP RATE, DATE OF LISTING, DATE OF ALLOTMENT, REDEMPTION DATE, REDEMPTION AMT, CONVERSION DATE, CONVERSION AMT, INTEREST PAYMENT DT\n"
    text = (
        header
        + "NSDC-SE,National Skill Development Corporation,N0,10,10,1,,22-OCT-2026,,16-OCT-2029,,,,,INS08SO12012\n"
        + "OTHER,Some Trust,SE,1,1,1,,22-OCT-2026,,16-OCT-2029,,,,,INS08SO12020\n"
        + "0ABCL31,Aditya Birla Capital Limited,N0,100000,100000,1,0,02-JUL-2026,,25-JUN-2031,,,,,INE674K07150\n"
    )
    result = parse_debt(text)
    assert [r["isin"] for r in result.rows] == ["INE674K07150"]
    assert result.excluded == 2
    assert result.skipped == 0
    assert is_social_exchange("MJHZCZP-SE", "N0")
    assert not is_social_exchange("0ABCL31", "N0")


def test_nse_sgb_json_carries_symbol_and_issue_price():
    result = parse_nse_sgb(read("nse_sgb_sample.json"))
    assert [(r["nse_symbol"], r["issue_price"]) for r in result.rows] == [
        ("SGBDE31III", Decimal("6149.00")),
        ("SGBJUN28", Decimal("4627.00")),
        ("SGBN28VIII", Decimal("5127.00")),
    ]
    assert result.skipped == 1  # no price
    assert all(r["isin"] is None for r in result.rows)


def test_nse_ratings_json_sets_rating_and_as_of():
    result = parse_nse_ratings(read("nse_ratings_sample.json"), TODAY)
    assert result.skipped == 1  # bad ISIN
    assert result.excluded == 1  # -SE symbol
    rows = by_isin(result.rows)
    scl = rows["INE148I07UR1"]
    assert scl["rating"] == "AA/Stable, AA/Stable"
    assert scl["rating_agency"] == "CRISIL, ICRA"
    assert scl["rating_as_of"] == TODAY
    assert scl["coupon_rate"] == Decimal("10.030")
    assert scl["maturity_date"] == date(2031, 9, 25)
    rec = rows["INE020B07GX4"]
    assert rec["rating"] is None and rec["rating_agency"] is None and rec["rating_as_of"] is None


def test_nse_ratings_rejects_malformed_json_shape():
    with pytest.raises(ValueError, match="data list"):
        parse_nse_ratings('{"data": 5}', TODAY)


def test_seed_sgb_csv_with_empty_cells():
    result = parse_seed_sgb(read("seed_sgb_sample.csv"))
    assert result.skipped == 2  # bad ISIN, missing series_name
    rows = by_isin(result.rows)
    assert len(rows) == 3
    full = rows["IN0020200104"]
    assert full["name"] == "SGB 2020-21 Series III"
    assert full["issuer"] == "Government of India"
    assert full["bond_type"] == "sgb"
    assert full["nse_symbol"] == "SGBJUN28" and full["nse_series"] == "GB"
    assert full["issue_date"] == date(2020, 6, 16)
    assert full["maturity_date"] == date(2028, 6, 16)
    assert full["coupon_rate"] == Decimal("2.500")
    assert full["issue_price"] == Decimal("4677.00")
    assert full["face_value"] is None
    empty = rows["IN0020150101"]
    assert empty["nse_symbol"] is None and empty["nse_series"] is None
    assert empty["issue_date"] is None and empty["maturity_date"] is None
    assert empty["coupon_rate"] is None and empty["issue_price"] is None


def test_seed_tax_free_csv_kinds():
    result = parse_seed_tax_free(read("seed_tax_free_sample.csv"))
    assert result.skipped == 1  # unknown kind
    rows = by_isin(result.rows)
    assert rows["INE020B07GX4"]["bond_type"] == "tax_free"
    assert rows["INE020B07GX4"]["name"] == "REC Limited 7.38% Tax-free Dec 2027"
    assert rows["INE020B07GX4"]["maturity_date"] == date(2027, 12, 19)
    pfc = rows["INE134E07ZZ9"]
    assert pfc["bond_type"] == "other"
    assert pfc["name"] == "PFC 54EC 5.25% 2026"
    assert rows["INE134E07AA1"]["name"] == "PFC Capital Gain Bonds 54EC"
    assert rows["INE134E07AA1"]["coupon_rate"] is None


def test_tax_free_display_name_rule():
    assert tax_free_display_name("REC Limited", Decimal("7.380"), date(2027, 12, 19)) == "REC Limited 7.38% Tax-free Dec 2027"
    assert tax_free_display_name("NHAI", Decimal("8.100"), date(2029, 1, 5)) == "NHAI 8.1% Tax-free Jan 2029"
    assert tax_free_display_name("IRFC", Decimal("8.000"), date(2030, 2, 1)) == "IRFC 8% Tax-free Feb 2030"
    assert tax_free_display_name("REC Limited", None, date(2027, 12, 19)) == "REC Limited Tax-free bond 2027"
    assert tax_free_display_name("REC Limited", None, None) == "REC Limited Tax-free bond"
    assert len(tax_free_display_name("X" * 400, Decimal("7"), date(2027, 1, 1))) == 300


def test_tax_free_seed_name_ignores_long_csv_name():
    csv_text = (
        "isin,issuer,name,kind,coupon_rate,maturity_date\n"
        "INE020B07GH7,REC Limited,8.12% -for categories I & II Tax Free Secured Bonds Series-2,tax_free,8.12,2027-03-27\n"
        "INE020B07GY2,REC Limited,Long NSDL name,tax_free,,\n"
    )
    rows = by_isin(parse_seed_tax_free(csv_text).rows)
    assert rows["INE020B07GH7"]["name"] == "REC Limited 8.12% Tax-free Mar 2027"
    assert rows["INE020B07GY2"]["name"] == "REC Limited Tax-free bond"


def test_merge_priority_seed_beats_debt_and_fills_gaps():
    rows, counts, skipped, extra = build_rows(_all_sources(), TODAY)
    merged = by_isin(rows)
    assert counts == {
        "debt": 8, "bhav": 3, "seed_sgb": 3, "seed_tax_free": 3, "nse_ratings": 2, "nse_sgb": 2,
    }
    assert skipped == 7
    assert extra["excluded"] == 1
    assert extra["source_errors"] == {"nsdl": "not provided"}
    rec = merged["INE020B07GX4"]
    assert rec["name"] == "REC Limited 7.38% Tax-free Dec 2027"  # seed name beats debt name
    assert rec["nse_symbol"] == "738REC27TF"  # debt fills what the seed lacks
    assert rec["face_value"] == Decimal("1000.00")
    assert rec["bond_type"] == "tax_free"
    assert rec["sources"] == ["debt", "nse_ratings", "seed_tax_free"]
    sgb = merged["IN0020200104"]
    assert sgb["name"] == "SGB 2020-21 Series III"  # seed beats bhav name
    assert sgb["issue_price"] == Decimal("4677.00")  # seed beats nse_sgb (4627)
    assert sgb["sources"] == ["bhav", "nse_sgb", "seed_sgb"]
    assert merged["IN0020200286"]["issue_price"] == Decimal("5127.00")  # only nse_sgb has it
    assert merged["IN0020200286"]["sources"] == ["bhav", "nse_sgb"]
    assert merged["IN0020210186"]["sources"] == ["debt"]


def test_rating_only_comes_from_nse_ratings():
    rows, *_ = build_rows(_all_sources(), TODAY)
    merged = by_isin(rows)
    scl = merged["INE148I07UR1"]
    assert (scl["rating"], scl["rating_agency"], scl["rating_as_of"]) == (
        "AA/Stable, AA/Stable", "CRISIL, ICRA", TODAY,
    )
    assert scl["name"] == "Sammaan Capital Limited 10.03% 25 Sep 2031 (1003SCL31A)"
    assert "INE000000000" not in merged  # ratings never create bonds
    assert "INS21BF12019" not in merged  # SSE
    unrated = [r for r in rows if r["rating"] is not None]
    assert [r["isin"] for r in unrated] == ["INE148I07UR1"]


def test_seed_only_rows_are_inserted_and_matured_ones_inactive():
    rows, *_ = build_rows(_all_sources(), TODAY)
    merged = by_isin(rows)
    assert merged["IN0020150085"]["is_active"] is False  # matured 2023
    assert merged["IN0020150101"]["is_active"] is True  # maturity unknown
    assert merged["INE134E07ZZ9"]["is_active"] is False  # 54EC matured 2026-03-31
    assert merged["INE134E07AA1"]["is_active"] is True
    assert merged["IN0020200104"]["is_active"] is True  # also traded, maturity in the future


def test_missing_optional_sources_are_reported_not_fatal():
    rows, counts, _, extra = build_rows(make_sources(extra_errors={"nse_ratings": "URLError: down"}), TODAY)
    assert len(rows) == 11  # 8 debt + 3 bhav SGBs
    assert set(counts) == {"debt", "bhav"}
    assert extra["source_errors"] == {
        "nse_ratings": "URLError: down",
        "seed_sgb": "not provided",
        "seed_tax_free": "not provided",
        "nse_sgb": "not provided",
        "nsdl": "not provided",
    }


def test_broken_optional_payloads_are_recorded():
    sources = make_sources(nse_sgb=b"<html>", nse_ratings="{}", seed_sgb="isin,series_name\n", seed_tax_free="")
    rows, _, _, extra = build_rows(sources, TODAY)
    assert len(rows) == 11
    assert set(extra["source_errors"]) == {"nse_sgb", "nse_ratings", "seed_sgb", "seed_tax_free", "nsdl"}


def test_merge_rows_pure_priority_and_tags():
    low = _bare("INE000000001", name="Low", coupon_rate=Decimal("1.000"), bond_type="corporate")
    high = _bare("INE000000001", name="High", bond_type="government")
    rated = _bare("INE000000001", rating="AAA", rating_agency="ICRA", rating_as_of=TODAY)
    rows = merge_rows(
        {"debt": [high], "bhav": [low], "nse_ratings": [rated]},
        {"debt": TODAY, "bhav": date(2026, 10, 23), "nse_ratings": TODAY},
    )
    (row,) = rows
    assert (row["name"], row["bond_type"], row["coupon_rate"]) == ("High", "government", Decimal("1.000"))
    assert row["rating"] == "AAA"
    assert row["sources"] == ["bhav", "debt", "nse_ratings"]
    assert row["last_seen"] == TODAY


def test_missing_sources_lists_tags_that_did_not_run():
    _, _, _, extra = build_rows(_all_sources(nsdl=read("nsdl_sample.csv")), TODAY)
    assert extra["missing_sources"] == []
    _, _, _, extra = build_rows(make_sources(nse_sgb=b"<html>"), TODAY)
    assert extra["missing_sources"] == ["seed_sgb", "seed_tax_free", "nsdl", "nse_ratings", "nse_sgb"]
    _, _, _, extra = build_rows(_all_sources(nsdl=read("nsdl_sample.csv"), bhav=None, bhav_error="x"), TODAY)
    assert extra["missing_sources"] == ["bhav"]


def test_merged_tags_sql_keeps_only_validated_tags():
    sql = merged_tags_sql("bond_master", ["nse_sgb", "bhav"])
    assert "ARRAY['nse_sgb', 'bhav']::varchar[]" in sql
    assert "ARRAY[]::varchar[]" in merged_tags_sql("bond_master", [])
    with pytest.raises(ValueError):
        merged_tags_sql("bond_master", ["x'; drop"])


def _bare(isin: str, **values) -> dict:
    return _row(isin=isin, **values)
