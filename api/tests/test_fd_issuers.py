import io
import json
import zipfile
from datetime import date

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app
from app.models import FdIssuerMaster, FixedDeposit, RecurringDeposit
from app.services import fd_issuers
from app.services.fd_issuers import (
    UNKNOWN_ISSUER_MESSAGE,
    IssuerSources,
    build_rows,
    normalize_name,
    parse_bank_aliases,
    parse_dicgc_xlsx,
    parse_nbfc_seed,
    parse_razorpay,
    require_issuer,
)

TODAY = date(2026, 10, 28)

BANKS = {
    "SBIN": {"code": "SBIN", "type": "PSB"},
    "HDFC": {"code": "HDFC", "type": "Private"},
    "UJVN": {"code": "UJVN", "type": "SFB"},
    "ABBL": {"code": "ABBL", "type": "Foreign"},
    "ABPB": {"code": "ABPB", "type": "PB"},
    "ABHY": {"code": "ABHY", "type": "S-UCB"},
    "ABCX": {"code": "ABCX", "type": "DCCB"},
    "XXXX": {"code": "XXXX", "type": "Mystery"},
    "NONM": {"code": "NONM", "type": "PSB"},
}
NAMES = {
    "SBIN": "State Bank of India",
    "HDFC": "HDFC Bank",
    "UJVN": "Ujjivan Small Finance Bank",
    "ABBL": "AB Bank",
    "ABPB": "Aditya Birla Idea Payments Bank",
    "ABHY": "Abhyudaya Co-operative Bank",
    "ABCX": "Aurangabad District Central Co-operative Bank",
    "XXXX": "Mystery Bank",
    "ANDB": "Andhra Bank",  # merged away: in banknames only
    "ORPH": "Orphan Bank",
}
ALIASES = (
    "code,short_name,merged_into_code,merged_on,dicgc_name,source,note\n"
    "SBIN,SBI,,,,seed,\n"
    "ANDB,Andhra Bank,SBIN,2020-04-01,,seed,merged\n"
    "HDFC,HDFC,,,,seed,\n"
    "NOPE,,,,,seed,unknown code\n"
    "ORPH,,GONE,2020-04-01,,seed,target unknown\n"
    "ABBL,AB,,,A B BANK LIMITED,seed,override\n"
)
NBFC = (
    "code,name,short_name,category,regulator,reg_no,deposit_status,source,note\n"
    "BAJFIN,Bajaj Finance Limited,Bajaj Finance,nbfc,RBI,N-13.02,permitted,seed,\n"
    "LICHF,LIC Housing Finance Limited,LIC HFL,hfc,NHB,01.0003.01,prior_approval,seed,\n"
    "NODEP,No Deposits Finance,,nbfc,RBI,,not_permitted,seed,\n"
    "BADCAT,Bad Category,,bank,RBI,,permitted,seed,\n"
    "SBIN,Collides With Bank,,nbfc,RBI,,permitted,seed,\n"
)


def _shared(items):
    return "".join(f"<si><t>{item}</t></si>" for item in items)


def make_xlsx(sheets: dict[str, list[str]], hidden: tuple[str, ...] = ()) -> bytes:
    """Minimal xlsx: each sheet has a header row and one numbered row per bank name."""
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rid = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    strings: list[str] = ["Sl.No.", "Name of the Bank"]
    sheet_xml: list[str] = []
    for names in sheets.values():
        rows = ['<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>']
        for number, name in enumerate(names, 1):
            strings.append(name)
            rows.append(
                f'<row r="{number + 1}"><c r="A{number + 1}"><v>{number}</v></c>'
                f'<c r="B{number + 1}" t="s"><v>{len(strings) - 1}</v></c></row>'
            )
        sheet_xml.append(f'<worksheet {ns}><sheetData>{"".join(rows)}</sheetData></worksheet>')
    sheet_tags = "".join(
        f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"'
        + (' state="hidden"' if name in hidden else "")
        + "/>"
        for i, name in enumerate(sheets, 1)
    )
    rels = "".join(
        f'<Relationship Id="rId{i}" Type="worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", f"<workbook {ns} {rid}><sheets>{sheet_tags}</sheets></workbook>")
        archive.writestr("xl/_rels/workbook.xml.rels", f"<Relationships>{rels}</Relationships>")
        archive.writestr("xl/sharedStrings.xml", f"<sst {ns}>{_shared(strings)}</sst>")
        for i, xml in enumerate(sheet_xml, 1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", xml)
    return buffer.getvalue()


DICGC = make_xlsx(
    {
        "Hidden": ["Should Not Appear"],
        "Public Sector Banks": ["STATE BANK OF INDIA"],
        "Private Sector Banks": ["The HDFC Bank Ltd."],
        "Foreign Banks": ["A B BANK LIMITED", "Some Other Foreign Bank"],
        "UCBs": ["ABHYUDAYA CO-OP. BANK LTD", "Unclaimed &amp; Co Urban Bank"],
    },
    hidden=("Hidden",),
)


def sources(**overrides) -> IssuerSources:
    base = {
        "banks_json": json.dumps(BANKS),
        "banknames_json": json.dumps(NAMES),
        "dicgc_xlsx": DICGC,
        "seed_banks": ALIASES,
        "seed_nbfc": NBFC,
    }
    base.update(overrides)
    return IssuerSources(**base)


def by_code(rows):
    return {r["code"]: r for r in rows}


# --- Parsing -----------------------------------------------------------------------------


def test_type_category_map_and_payments_do_not_accept_deposits():
    rows, names, skipped = parse_razorpay(json.dumps(BANKS), json.dumps(NAMES))
    rows = by_code(rows)
    assert {c: r["category"] for c, r in rows.items()} == {
        "SBIN": "public_sector", "HDFC": "private_sector", "UJVN": "small_finance",
        "ABBL": "foreign", "ABPB": "payments", "ABHY": "urban_coop", "ABCX": "district_coop",
    }  # fmt: skip
    assert skipped == 2  # unknown type + no name
    assert rows["ABPB"]["accepts_deposits"] is False
    assert rows["SBIN"]["accepts_deposits"] is True
    assert rows["SBIN"]["name"] == "State Bank of India"
    assert names["ANDB"] == "Andhra Bank"


def test_every_razorpay_type_maps_to_a_known_category():
    from app.models.fd_issuer_master import CATEGORIES

    assert set(fd_issuers.TYPE_CATEGORY.values()) <= set(CATEGORIES)
    assert set(fd_issuers.TYPE_CATEGORY) == {
        "PSB", "Private", "SFB", "Foreign", "RRB", "LAB", "PB", "SCB", "DCCB", "S-UCB", "O-UCB"
    }  # fmt: skip


def test_razorpay_rejects_unexpected_shape():
    with pytest.raises(ValueError):
        parse_razorpay("[]", "{}")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The HDFC Bank Ltd.", "HDFC BANK"),
        ("ABHYUDAYA CO-OP. BANK LTD", "ABHYUDAYA COOP BANK"),
        ("Abhyudaya Co-operative Bank", "ABHYUDAYA COOP BANK"),
        ("Akhand Anand Co.op Bank", "AKHAND ANAND COOP BANK"),
        ("Aditya Cooperative Bank Limited", "ADITYA COOP BANK"),
        ("Johnson &amp; Co", "JOHNSON AND CO"),
        ("Johnson & Co", "JOHNSON AND CO"),
        ("  Bank,  of   India. ", "BANK OF INDIA"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw.replace("&amp;", "&")) == expected


def test_dicgc_xlsx_parse_skips_hidden_sheets_and_header_and_decodes_entities():
    found = parse_dicgc_xlsx(DICGC)
    assert ("Hidden", "Should Not Appear") not in found
    assert ("Public Sector Banks", "STATE BANK OF INDIA") in found
    assert ("UCBs", "Unclaimed & Co Urban Bank") in found
    assert len(found) == 6
    assert all(name != "Name of the Bank" for _, name in found)


def test_dicgc_xlsx_without_rows_is_an_error():
    with pytest.raises(ValueError):
        parse_dicgc_xlsx(make_xlsx({"Empty": []}))


def test_seed_parsers():
    aliases = {a["code"]: a for a in parse_bank_aliases(ALIASES)}
    assert aliases["ANDB"]["merged_into_code"] == "SBIN"
    assert aliases["ANDB"]["merged_on"] == date(2020, 4, 1)
    assert aliases["SBIN"]["merged_into_code"] is None
    assert aliases["ABBL"]["dicgc_name"] == "A B BANK LIMITED"
    rows, skipped = parse_nbfc_seed(NBFC)
    rows = by_code(rows)
    assert skipped == 1  # bad category
    assert rows["BAJFIN"]["accepts_deposits"] is True
    assert rows["LICHF"]["accepts_deposits"] is True
    assert rows["LICHF"]["category"] == "hfc"
    assert rows["NODEP"]["accepts_deposits"] is False
    assert rows["BAJFIN"]["reg_no"] == "N-13.02"


# --- Build -------------------------------------------------------------------------------


def test_build_rows_matches_dicgc_uses_overrides_and_merges():
    built = build_rows(sources(), TODAY)
    rows = by_code(built.rows)
    assert built.errors == {}
    assert built.ran == {"razorpay", "dicgc", "seed_banks", "seed_nbfc"}
    assert rows["POST"]["category"] == "post_office"
    assert rows["POST"]["regulator"] is None
    assert rows["POST"]["short_name"] == "India Post"
    # DICGC: normalisation ("The HDFC Bank Ltd." == "HDFC Bank") and override ("A B BANK LIMITED")
    assert rows["SBIN"]["dicgc_insured"] is True
    assert rows["HDFC"]["dicgc_insured"] is True
    assert rows["ABBL"]["dicgc_insured"] is True
    assert rows["ABHY"]["dicgc_insured"] is True
    assert rows["UJVN"]["dicgc_insured"] is None  # unmatched stays unknown
    assert rows["SBIN"]["short_name"] == "SBI"
    assert set(rows["SBIN"]["sources"]) == {"razorpay", "dicgc", "seed_banks"}
    assert built.dicgc_names == 6
    assert built.unmatched_names == {"small_finance": ["Ujjivan Small Finance Bank"]}
    assert built.dicgc_unclaimed == 2
    assert built.unclaimed_names == ["Some Other Foreign Bank", "Unclaimed & Co Urban Bank"]
    # merged bank only in banknames: inserted inactive with the category of the bank it merged into
    assert rows["ANDB"]["is_active"] is False
    assert rows["ANDB"]["merged_into_code"] == "SBIN"
    assert rows["ANDB"]["merged_on"] == date(2020, 4, 1)
    assert rows["ANDB"]["category"] == "public_sector"
    # aliases with an unknown code or an unknown merge target are noted and not inserted
    assert any("NOPE" in n for n in built.notes)
    assert any("ORPH" in n for n in built.notes)
    assert "ORPH" not in rows and "NOPE" not in rows
    # NBFC seed
    assert rows["BAJFIN"]["sources"] == ["seed_nbfc"]
    assert "NODEP" in rows and rows["NODEP"]["accepts_deposits"] is False
    assert "BADCAT" not in rows
    assert rows["SBIN"]["name"] == "State Bank of India"  # collision with the NBFC seed ignored
    assert all(r["last_seen"] == TODAY for r in built.rows)


def test_merged_bank_keeps_deposit_flag_and_skips_dicgc():
    built = build_rows(sources(), TODAY)
    rows = by_code(built.rows)
    assert rows["ANDB"]["accepts_deposits"] is True
    assert rows["ANDB"]["dicgc_insured"] is None  # merged banks are not matched
    assert rows["SBIN"]["is_active"] is True


def test_optional_sources_never_abort_each_other():
    built = build_rows(sources(dicgc_xlsx=b"not a zip", seed_nbfc=None), TODAY)
    assert "dicgc" in built.errors
    assert built.ran == {"razorpay", "seed_banks"}
    rows = by_code(built.rows)
    assert rows["SBIN"]["dicgc_insured"] is None
    assert rows["SBIN"]["short_name"] == "SBI"
    assert "BAJFIN" not in rows


def test_razorpay_failure_leaves_banks_out_but_keeps_other_sources():
    built = build_rows(
        sources(banks_json=None, banknames_json=None, errors={"razorpay": "URLError: down"}), TODAY
    )
    assert built.errors["razorpay"] == "URLError: down"
    assert "razorpay" not in built.ran
    assert {r["code"] for r in built.rows} == {"POST", "BAJFIN", "LICHF", "NODEP", "SBIN"}  # SBIN here is the NBFC seed row


def test_broken_razorpay_json_is_reported_not_raised():
    built = build_rows(sources(banks_json="{not json"), TODAY)
    assert "razorpay" in built.errors
    assert {r["code"] for r in built.rows} >= {"POST", "BAJFIN"}


def test_seed_codes_resolve_via_ifsc_prefix():
    banks = {
        "ESAF": {"type": "SFB", "ifsc": "ESMF0000001"},
        "AUBL": {"type": "SFB", "ifsc": "AUBL0002011"},
        "FINF": {"type": "SFB", "ifsc": "FSFB0000001"},
        "ACOX": {"type": "O-UCB", "ifsc": "HDFC0CACOOB"},
        "HDFC": {"type": "Private", "ifsc": "HDFC0000001"},
    }
    names = {"ESMF": "ESAF SFB", "ESAF": "ESAF SFB", "AUBL": "AU SFB", "FINF": "Fincare", "FSFB": "Fincare",
             "ACOX": "Acme Coop", "HDFC": "HDFC Bank"}  # fmt: skip
    seed = (
        "code,short_name,merged_into_code,merged_on,dicgc_name,source,note\n"
        "ESMF,ESAF,,,,seed,\n"
        "FSFB,Fincare,AUBL,2024-04-01,,seed,\n"
        "HDFC,HDFC,,,,seed,\n"
    )
    built = build_rows(
        IssuerSources(banks_json=json.dumps(banks), banknames_json=json.dumps(names), seed_banks=seed), TODAY
    )
    rows = by_code(built.rows)
    assert built.notes == []
    assert rows["ESAF"]["short_name"] == "ESAF"
    assert rows["FINF"]["merged_into_code"] == "AUBL" and rows["FINF"]["is_active"] is False
    assert "ESMF" not in rows and "FSFB" not in rows
    assert fd_issuers.ifsc_prefix_map(json.dumps(banks)) == {"ESMF": "ESAF", "FSFB": "FINF"}


def test_reserve_bank_and_general_post_office_are_not_issuers():
    banks = {"RBIN": {"type": "PSB"}, "GPOX": {"type": "PSB"}, "SBIN": {"type": "PSB"}}
    names = {"RBIN": "Reserve Bank Of India", "GPOX": "General Post Office", "SBIN": "State Bank of India"}
    rows, _, _ = parse_razorpay(json.dumps(banks), json.dumps(names))
    flags = {r["code"]: r["accepts_deposits"] for r in rows}
    assert flags == {"RBIN": False, "GPOX": False, "SBIN": True}


# --- Fuzzy DICGC matching ----------------------------------------------------------------


def _fuzzy_build(bank_names: dict[str, str], dicgc_names: list[str], sheet: str = "UCBs", btype: str = "O-UCB"):
    banks = {code: {"type": btype} for code in bank_names}
    return by_code(
        build_rows(
            IssuerSources(
                banks_json=json.dumps(banks),
                banknames_json=json.dumps(bank_names),
                dicgc_xlsx=make_xlsx({sheet: dicgc_names}),
            ),
            TODAY,
        ).rows
    )


def test_fuzzy_dicgc_accepts_a_unique_near_match():
    rows = _fuzzy_build(
        {"AAAA": "Sri Venkateswara Urban Co-operative Bank Ltd", "BBBB": "Mahalaxmi Co-op Bank"},
        ["SRI VENKATESHWARA SAHAKARI BANK LTD", "MAHALAKSHMI DISTANT COOP BANK", "UNRELATED THING"],
    )
    assert rows["AAAA"]["dicgc_insured"] is True
    assert "dicgc" in rows["AAAA"]["sources"]
    assert rows["BBBB"]["dicgc_insured"] is None  # ratio below 0.92 stays unmatched


def test_fuzzy_dicgc_rejects_ambiguous_and_low_ratio():
    rows = _fuzzy_build(
        {"AAAA": "Ganesh Nagari Sahakari Bank", "BBBB": "Shivaji Co-op Bank"},
        ["GANESHA NAGARI SAHAKARI BANK", "GANESHH NAGARI SAHAKARI BANK", "SHIVAJI KRISHNA BANK"],
    )
    assert rows["AAAA"]["dicgc_insured"] is None  # two near-identical candidates: margin too small
    assert rows["BBBB"]["dicgc_insured"] is None  # too different


def test_fuzzy_dicgc_stays_in_its_sheet_and_claims_once():
    # right name, wrong sheet (RRB name offered for an urban co-op bank)
    rows = _fuzzy_build({"AAAA": "Pragati Urban Bank"}, ["PRAGATHI BANK"], sheet="RRB")
    assert rows["AAAA"]["dicgc_insured"] is None
    # two banks wanting the same DICGC name: neither is accepted
    rows = _fuzzy_build(
        {"AAAA": "Pragati Urban Bank", "BBBB": "Pragathi Bank"}, ["PRAGATI DISTRICT BANK"]
    )
    assert rows["AAAA"]["dicgc_insured"] is None and rows["BBBB"]["dicgc_insured"] is None


# --- require_issuer / assets -------------------------------------------------------------


def _add_issuers(session):
    session.add_all(
        [
            FdIssuerMaster(code="SBIN", name="State Bank of India", short_name="SBI", category="public_sector"),
            FdIssuerMaster(code="ABPB", name="Aditya Birla Payments Bank", category="payments", accepts_deposits=False),
            FdIssuerMaster(code="LONG", name="L" * 250, category="nbfc"),
        ]
    )
    session.commit()


def test_require_issuer_rules(db_session):
    Base.metadata.create_all(db_session.get_bind(), tables=[FdIssuerMaster.__table__])
    _add_issuers(db_session)
    ids = {i.code: i.id for i in db_session.query(FdIssuerMaster)}
    assert require_issuer(db_session, ids["SBIN"]).code == "SBIN"
    for bad in (ids["ABPB"], 9999, 0, 2**40):
        with pytest.raises(RequestValidationError) as exc:
            require_issuer(db_session, bad)
        error = exc.value.errors()[0]
        assert error["loc"] == ("body", "issuer_id")
        assert error["msg"] == UNKNOWN_ISSUER_MESSAGE == "Select a bank or issuer from the list"


FD = {
    "bank": "typed by user", "principal": 100000, "rate": 7, "start_date": "2026-10-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
RD = {
    "bank": "typed by user", "monthly_instalment": 5000, "rate": 7, "start_date": "2026-10-01",
    "compounding": "quarterly", "tenure_years": 1,
}  # fmt: skip


@pytest.fixture
def client(auth_engine, auth_settings):
    Base.metadata.create_all(
        auth_engine,
        tables=[m.__table__ for m in (FdIssuerMaster, FixedDeposit, RecurringDeposit)],
    )
    factory = sessionmaker(bind=auth_engine, expire_on_commit=False)
    with factory() as session:
        _add_issuers(session)

    def override():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def headers(client, auth_settings):
    auth_settings.allowed_emails = ["a@example.com"]
    body = client.post(
        "/api/auth/signup", json={"email": "a@example.com", "password": "a-long-password"}
    ).json()
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest.mark.parametrize("slug", ["fd", "rd"])
def test_issuer_snapshot_on_create_and_update(client, headers, slug):
    body = dict(FD if slug == "fd" else RD)
    created = client.post(f"/api/assets/{slug}", json=body | {"issuer_id": 1}, headers=headers)
    assert created.status_code == 201
    data = created.json()
    assert data["issuer_id"] == 1
    assert data["bank"] == "SBI"  # short_name wins over the typed value
    long_issuer = client.put(
        f"/api/assets/{slug}/{data['id']}", json=body | {"issuer_id": 3}, headers=headers
    )
    assert long_issuer.status_code == 200
    assert long_issuer.json()["bank"] == "L" * 200
    free_text = client.post(f"/api/assets/{slug}", json=body, headers=headers).json()
    assert free_text["issuer_id"] is None
    assert free_text["bank"] == "typed by user"


@pytest.mark.parametrize("issuer_id", [2, 999])
def test_unusable_issuer_is_a_422_with_the_shared_message(client, headers, issuer_id):
    response = client.post("/api/assets/fd", json=FD | {"issuer_id": issuer_id}, headers=headers)
    assert response.status_code == 422
    assert UNKNOWN_ISSUER_MESSAGE in json.dumps(response.json())
