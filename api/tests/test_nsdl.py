from datetime import date
from decimal import Decimal

import pytest

from app.jobs import nsdl_convert as nc
from app.services.bond_master import build_rows, merge_rows, nsdl_display_name, parse_nsdl, _row
from tests.market_helpers import TODAY, by_isin, make_sources, read

AS_OF = date(2026, 10, 27)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("10-11-2023", "2023-11-10"), ("01-02-2030 ", "2030-02-01"), ("31-12-9999", "9999-12-31"),
     ("", ""), (None, ""), ("2023-11-10", ""), ("32-01-2020", "")],
)
def test_normalise_date(raw, expected):
    assert nc.normalise_date(raw) == expected


def test_perpetual_date_clears_maturity():
    assert nc.is_perpetual("31-12-9999") and not nc.is_perpetual("31-12-2030")
    out = nc.convert_row({"ISIN": "INE0NSDL0029", "Date of Redemption/Conversion": "31-12-9999"}, "2026-10-27")
    assert (out["maturity_date"], out["is_perpetual"]) == ("", 1)


@pytest.mark.parametrize(
    ("raw", "frequency", "expected"),
    [("7.79", "yearly", "7.79"), ("9.05%", "yearly", "9.05"), (" 8 ", "", "8"), ("", "", ""),
     ("NIFTY50", "", ""), ("8.40% IRR", "", ""), ("15% XIRR AND 7.26 GSEC LINKED", "", ""),
     ("0", "on_maturity", "0"), ("0", "", "0"), ("0", "half_yearly", ""), ("-1", "", ""), ("1000", "", "")],
)
def test_normalise_coupon(raw, frequency, expected):
    assert nc.normalise_coupon(raw, frequency) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Once a year", "yearly"), ("Twelve times a year", "monthly"), ("QUARTERLY", "quarterly"),
     ("Four times a year", "quarterly"), ("Twice a year", "half_yearly"), ("On Maturity", "on_maturity"),
     ("On Maturity/Put-Call", "on_maturity"), ("No Occurence", "none"),
     ("Irregular Occurence", "irregular"), ("At Any Time", "irregular"), ("Every 5 years", "irregular"),
     ("", ""), (None, ""), ("whatever", "")],
)
def test_normalise_frequency(raw, expected):
    assert nc.normalise_frequency(raw) == expected


@pytest.mark.parametrize(
    ("raw", "ratings", "agencies"),
    [
        ("CRISIL AAA/Stable ();CARE AAA/Stable ()", "AAA/Stable", "CRISIL, CARE"),
        ("ICRA AA+/Stable", "AA+/Stable", "ICRA"),
        ("CRISIL AA/Stable ();ICRA A/Positive", "AA/Stable, A/Positive", "CRISIL, ICRA"),
        ("CRISIL AAA/Stable;CRISIL AAA/Stable ()", "AAA/Stable", "CRISIL"),
        ("BWR BB-/Stable () (ISSUER NOT COOPERATING*);IND AA+/Stable ()", "BB-/Stable, AA+/Stable", "BWR, IND"),
        ("BWR C/No Outlook () (ISSUER NOT COOPERATING*)", "C/No Outlook", "BWR"),
        ("ACUITE PP-MLD  BBB/Stable ()", "PP-MLD BBB/Stable", "ACUITE"),
        ("IND WITHDRAWN/No Outlook ()", "", ""),
        ("CARE WD;ICRA AA/Stable", "AA/Stable", "ICRA"),
        ("IVR A/Stable", "A/Stable", "INFOMERICS"),
        ("", "", ""),
        (None, "", ""),
    ],
)
def test_split_ratings(raw, ratings, agencies):
    assert nc.split_ratings(raw) == (ratings, agencies)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RELIANCE INDUSTRIES LIMITED", "Reliance Industries Limited"),
        ("HDFC BANK LIMITED", "HDFC Bank Limited"),
        ("NTPC LIMITED", "NTPC Limited"),
        ("L&T FINANCE LIMITED", "L&T Finance Limited"),
        ("REC LIMITED", "REC Limited"),
        ("TATA CAPITAL HOUSING FINANCE LTD", "Tata Capital Housing Finance Ltd"),
        ("WELSPUN AUNTA-SIMARIA PROJECT PRIVATE LIMITED", "Welspun Aunta-Simaria Project Private Limited"),
        ("GOODWATTS WTE (INDIA) PVT LTD", "Goodwatts Wte (India) Pvt Ltd"),
        ("  Mixed   case LTD ", "Mixed Case Ltd"),
        ("", ""),
    ],
)
def test_title_issuer(raw, expected):
    assert nc.title_issuer(raw) == expected


def test_choice_normalisers():
    assert nc.normalise_choice("Private Placement (non-EBP)", nc.ISSUE_MODES) == "private"
    assert nc.normalise_choice("Private Placement (EBP)", nc.ISSUE_MODES) == "private"
    assert nc.normalise_choice("Public Issue", nc.ISSUE_MODES) == "public"
    assert nc.normalise_choice("Rights Issue", nc.ISSUE_MODES) == "rights"
    assert nc.normalise_choice("Bonus", nc.ISSUE_MODES) == "bonus"
    assert nc.normalise_choice("Scheme of Arrangement", nc.ISSUE_MODES) == "other"
    assert nc.normalise_choice("", nc.ISSUE_MODES) == ""
    assert nc.normalise_choice("Public Sector Undertaking (PSU)", nc.OWNERSHIPS) == "psu"
    assert nc.normalise_choice("Non PSU", nc.OWNERSHIPS) == "non_psu"
    assert nc.normalise_choice("Issuer under ILDM Regulations", nc.OWNERSHIPS) == "ildm"
    assert nc.normalise_choice("Taxfree", nc.TAX_CATEGORIES) == "taxfree"
    assert nc.normalise_choice("Debentures", nc.INSTRUMENT_TYPES) == "debentures"
    assert nc.normalise_choice("Compounding", nc.COUPON_TYPES) == "compounding"
    assert nc.normalise_status("Suspended") == "suspended"
    assert nc.normalise_status("Active ") == "active"


def test_convert_rows_normalises_sorts_and_dedupes():
    header = (
        "ISIN", "Name of Issuer", "Type of Instrument", "Mode of Issue", "Category of Issue",
        "Face Value(in Rs.)", "Issue Size(in Rs.)", "Date of Allotment", "Date of Redemption/Conversion",
        "Coupon Rate (%)", "Coupon Type", "Frequency of Interest Payment", "Credit Rating",
        "Type of Issuer-Ownership", "Instrument Status", None,
    )  # fmt: skip
    one = (
        "INE002A07809", "RELIANCE INDUSTRIES LIMITED ", "Debentures", "Private Placement (non-EBP)", "Taxable",
        "100000.000", "200000000000", "10-11-2023", "10-11-2033", "7.79", "Simple", "Once a year",
        "CRISIL AAA/Stable ();CARE AAA/Stable ()", "Non PSU", "Active", None,
    )  # fmt: skip
    two = ("INE000A00001", "x", *("",) * 14)
    rows = [header, one, two, one, ("NOPE", *("",) * 15)]
    out = nc.convert_rows(rows, "2026-10-27")
    assert [r["isin"] for r in out] == ["INE000A00001", "INE002A07809"]
    r = out[1]
    assert r == {
        "isin": "INE002A07809", "issuer": "Reliance Industries Limited", "instrument_type": "debentures",
        "issue_mode": "private", "tax_category": "taxable", "face_value": "100000", "issue_size": "200000000000",
        "allotment_date": "2023-11-10", "maturity_date": "2033-11-10", "is_perpetual": 0, "coupon_rate": "7.79",
        "coupon_type": "simple", "interest_frequency": "yearly", "rating": "AAA/Stable",
        "rating_agency": "CRISIL, CARE", "issuer_ownership": "non_psu", "status": "active", "as_of": "2026-10-27",
    }
    assert list(r) == nc.COLUMNS


def test_write_csv_roundtrips_through_parse_nsdl(tmp_path):
    record = nc.convert_row({"ISIN": "INE002A07809", "Name of Issuer": "RELIANCE INDUSTRIES LIMITED"}, "2026-10-27")
    path = tmp_path / "out.csv"
    nc.write_csv([record], path)
    assert path.read_text().splitlines()[0] == ",".join(nc.COLUMNS)
    (row,) = parse_nsdl(path.read_text()).rows
    assert row["issuer"] == "Reliance Industries Limited"


def test_xlsx_roundtrip_with_openpyxl(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["ISIN", "Name of Issuer", "Coupon Rate (%)", "Date of Redemption/Conversion"])
    sheet.append(["INE002A07809", "REC LIMITED", "9.05%", "31-12-9999"])
    path = tmp_path / "list.xlsx"
    workbook.save(path)
    (out,) = nc.convert_rows(nc.read_xlsx(path), "2026-10-27")
    assert (out["issuer"], out["coupon_rate"], out["is_perpetual"], out["maturity_date"]) == ("REC Limited", "9.05", 1, "")


# --- nsdl source in the bond import ---------------------------------------------


def test_name_generation():
    d = date(2033, 6, 15)
    assert nsdl_display_name("Acme Limited", "debentures", Decimal("8.5"), d, False) == "Acme Limited 8.5% NCD Jun 2033"
    assert nsdl_display_name("Acme Limited", "bonds", Decimal("7.790"), d, False) == "Acme Limited 7.79% Bond Jun 2033"
    assert nsdl_display_name("Acme Limited", "", None, d, False) == "Acme Limited Bond Jun 2033"
    assert nsdl_display_name("Acme Limited", "bonds", Decimal("0.000"), None, True) == "Acme Limited Bond Perpetual"
    assert nsdl_display_name("Acme Limited", "debentures", Decimal("9"), None, False) == "Acme Limited 9% NCD"
    assert len(nsdl_display_name("X" * 400, "bonds", None, d, False)) == 300


def test_parse_nsdl_csv():
    result = parse_nsdl(read("nsdl_sample.csv"))
    assert len(result.rows) == 6
    assert result.skipped == 2  # blank issuer, bad ISIN
    rows = by_isin(result.rows)
    acme = rows["INE0NSDL0011"]
    assert acme["name"] == "Acme Finance Limited 8.5% NCD Jun 2033"
    assert acme["bond_type"] == "tax_free"
    assert (acme["coupon_type"], acme["interest_frequency"], acme["issuer_ownership"], acme["issue_mode"]) == (
        "compounding", "quarterly", "non_psu", "private",
    )
    assert acme["issue_size"] == Decimal("250000000.00")
    assert acme["issue_date"] == date(2023, 2, 1)
    assert acme["rating"] is None and acme["rating_as_of"] is None
    perp = rows["INE0NSDL0029"]
    assert perp["is_perpetual"] is True and perp["maturity_date"] is None
    assert perp["name"] == "Big Bank Limited Bond Perpetual"
    assert perp["bond_type"] is None and perp["issue_size"] is None
    toyota = rows["INE692Q07621"]
    assert (toyota["rating"], toyota["rating_agency"], toyota["rating_as_of"]) == ("AAA/Stable", "CRISIL", AS_OF)
    assert toyota["nsdl_status"] == "suspended"


def _merged():
    rows, counts, skipped, extra = build_rows(
        make_sources(
            nse_ratings=read("nse_ratings_sample.json"),
            seed_tax_free=read("seed_tax_free_sample.csv"),
            nsdl=read("nsdl_sample.csv"),
        ),
        TODAY,
    )
    return by_isin(rows), counts, extra


def test_nsdl_priority_over_debt_and_name_rule():
    merged, counts, extra = _merged()
    assert counts["nsdl"] == 6
    assert extra["source_errors"].get("nsdl") is None
    toyota = merged["INE692Q07621"]
    assert toyota["coupon_rate"] == Decimal("7.100")  # nsdl beats debt (7.08)
    assert toyota["name"] == "Toyota Financial Services India Limited 7.08% 18 Nov 2027 (708TFSIL27)"  # debt name kept
    assert toyota["nse_symbol"] == "708TFSIL27"
    assert toyota["interest_frequency"] == "half_yearly"
    assert toyota["bond_type"] == "corporate"
    assert toyota["sources"] == ["debt", "nsdl"]
    assert toyota["is_perpetual"] is False


def test_nsdl_seed_wins_name_and_taxfree_maps_bond_type():
    merged, _, _ = _merged()
    rec = merged["INE020B07GX4"]
    assert rec["name"] == "REC Limited 7.38% Tax-free Dec 2027"  # seed name beats debt and nsdl
    assert rec["bond_type"] == "tax_free"
    assert rec["issuer"] == "REC Limited"  # seed issuer beats nsdl
    assert rec["issue_date"] == date(2012, 12, 24)
    assert rec["sources"] == ["debt", "nsdl", "nse_ratings", "seed_tax_free"]
    acme = merged["INE0NSDL0011"]
    assert acme["bond_type"] == "tax_free" and acme["sources"] == ["nsdl"]


def test_rating_prefers_nse_ratings_over_nsdl():
    merged, _, _ = _merged()
    scl = merged["INE148I07UR1"]
    assert (scl["rating"], scl["rating_agency"], scl["rating_as_of"]) == ("AA/Stable, AA/Stable", "CRISIL, ICRA", TODAY)
    rec = merged["INE020B07GX4"]  # nse_ratings row has no rating -> nsdl fills it
    assert (rec["rating"], rec["rating_agency"], rec["rating_as_of"]) == ("AAA/Stable", "CRISIL, ICRA", AS_OF)
    assert merged["INE692Q07621"]["rating_as_of"] == AS_OF


def test_nsdl_only_rows_defaults_and_activity():
    merged, _, _ = _merged()
    perp = merged["INE0NSDL0029"]
    assert perp["bond_type"] == "corporate" and perp["is_active"] is True
    assert perp["name"] == "Big Bank Limited Bond Perpetual"
    old = merged["INE0NSDL0037"]
    assert old["is_active"] is False  # matured 2020, no exchange list keeps it alive
    assert old["coupon_rate"] == Decimal("0.000") and old["name"] == "Old Corp Limited Bond Jan 2020"
    assert merged["INE0NSDL0011"]["is_active"] is True


def test_is_perpetual_is_unknown_without_nsdl_and_kept_on_upsert():
    from app.services.bond_master import KEEP_COLUMNS

    assert "is_perpetual" in KEEP_COLUMNS
    rows, *_ = build_rows(make_sources(), TODAY)
    assert all(r["is_perpetual"] is None for r in rows)
    merged, _, _ = _merged()
    assert merged["INE0NSDL0029"]["is_perpetual"] is True
    assert merged["INE0NSDL0011"]["is_perpetual"] is False


def test_merge_rows_pure_nsdl_between_seed_and_debt():
    seed = _row(isin="INE000000001", name="Seed", bond_type="tax_free")
    nsdl = _row(isin="INE000000001", name="Nsdl", issuer="Nsdl Issuer", coupon_rate=Decimal("8"), bond_type=None)
    debt = _row(isin="INE000000001", name="Debt", issuer="Debt Issuer", coupon_rate=Decimal("7"), bond_type="corporate")
    (row,) = merge_rows(
        {"seed_tax_free": [seed], "nsdl": [nsdl], "debt": [debt]},
        {"seed_tax_free": TODAY, "nsdl": TODAY, "debt": TODAY},
    )
    assert (row["name"], row["issuer"], row["coupon_rate"], row["bond_type"]) == ("Seed", "Nsdl Issuer", Decimal("8"), "tax_free")
    (row,) = merge_rows({"nsdl": [nsdl], "debt": [debt]}, {"nsdl": TODAY, "debt": TODAY})
    assert (row["name"], row["issuer"], row["bond_type"]) == ("Debt", "Nsdl Issuer", "corporate")
