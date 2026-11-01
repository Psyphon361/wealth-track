from datetime import date
from decimal import Decimal

import pytest

from app.services import nps

LATEST = "\n".join(
    [
        "ID\tDATE OF NAV\tPFM NAME\tSCHEME ID\tSCHEME NAME\tNAV VALUE",
        "3\t2026-10-31\tSBI Pension Funds Pvt. Ltd.\tSM001003\tSBI PENSION FUND SCHEME E - TIER I\t53.6052",
        "4\t2026-10-30\tUTI Pension Fund Limited.\tSM002001\tUTI RETIREMENT SOLUTIONS PENSION FUND SCHEME- CENTRAL GOVT\t48.2669",
        "5\t2026-10-31\tLIC Pension Fund Ltd.\tSM003001\tLIC PENSION FUND SCHEME - CENTRAL GOVT\tabc",
        "6\t2026-10-31\tLIC Pension Fund Ltd.\tBAD\tBroken id row\t10",
        "7\t2026-10-31\tshort row",
        "3\t2026-10-31\tSBI Pension Funds Pvt. Ltd.\tSM001003\tDUPLICATE\t1.0",
    ]
)

HISTORY = "\n".join(
    [
        "ID\tDATE OF NAV\tPFM ID\tPFM NAME\tSCHEME ID\tSCHEME NAME\tNAV VALUE",
        "1\t2026-10-31\tPFM001\tSBI Pension Funds Pvt. Ltd.\tSM001025\tSBI DIRECT\t53.7111",
        "2\t2026-03-31\tPFM001\tSBI Pension Funds Pvt. Ltd.\tSM001003\tSBI E TIER I\t50.1000",
        "3\t2026-03-30\tPFM001\tSBI Pension Funds Pvt. Ltd.\tSM001003\tSBI E TIER I\t0",
        "4\t2026-03-27\tPFM001\tSBI Pension Funds Pvt. Ltd.\tSM001003\tSBI E TIER I\t49.9",
        "5\tnot-a-date\tPFM001\tSBI Pension Funds Pvt. Ltd.\tSM001003\tSBI E TIER I\t49.0",
    ]
)


def test_parse_latest():
    result = nps.parse_latest(LATEST)
    assert [r.scheme_id for r in result.rows] == ["SM001003", "SM002001", "SM003001"]
    first = result.rows[0]
    assert (first.pfm_code, first.pfm_name, first.tier, first.asset_class, first.is_active) == (
        "PFM001",
        "SBI Pension Funds Pvt. Ltd.",
        "I",
        "E",
        True,
    )
    assert [(n.scheme_id, n.nav, n.nav_date) for n in result.navs] == [
        ("SM001003", Decimal("53.6052"), date(2026, 10, 31)),
        ("SM002001", Decimal("48.2669"), date(2026, 10, 30)),
    ]
    assert result.file_date == date(2026, 10, 31)
    assert result.skipped == 3  # bad id, short row, duplicate id


def test_parse_history_keeps_only_requested_scheme():
    rows = nps.parse_history(HISTORY, "SM001003")
    assert rows == [
        (date(2026, 3, 27), Decimal("49.9000")),
        (date(2026, 3, 31), Decimal("50.1000")),
    ]
    assert nps.parse_history(HISTORY, "SM001025") == [(date(2026, 10, 31), Decimal("53.7111"))]


@pytest.mark.parametrize(
    ("scheme_id", "pfm"),
    [
        ("SM001003", "PFM001"),
        ("SM002001", "PFM002"),
        ("SM003001", "PFM003"),
        ("SM007001", "PFM007"),
        ("SM014022", "PFM014"),
        ("XX001003", None),
        ("SM1003", None),
    ],
)
def test_derive_pfm_code(scheme_id, pfm):
    assert nps.derive_pfm_code(scheme_id) == pfm


@pytest.mark.parametrize(
    ("name", "tier", "asset_class"),
    [
        ("SBI PENSION FUND SCHEME E - TIER I", "I", "E"),
        ("NPS TRUST A/C SBI PENSION FUND SCHEME E - TIER I DIRECT", "I", "E"),
        ("HDFC PENSION MANAGEMENT COMPANY LIMITED SCHEME C - TIER II", "II", "C"),
        ("SBI PENSION FUND SCHEME G - TIER I GS", "I", "G"),
        ("SBI PENSION FUND SCHEME A - TIER I", "I", "A"),
        ("SBI PENSION FUND SCHEME G - TIER II POP", "II", "G"),
        ("SBI PENSION FUND SCHEME - CENTRAL GOVT", None, "other"),
        ("SBI PENSION FUND SCHEME - STATE GOVT", None, "other"),
        ("NPS TRUST A/C-SBI PENSION FUNDS PRIVATE LIMITED- NPS LITE SCHEME - GOVT. PATTERN", None, "other"),
        ("SBI PENSION FUNDS PVT LTD SCHEME - CORPORATE-CG", None, "other"),
        ("NPS TRUST - A/C SBI PENSION FUND SCHEME - ATAL PENSION YOJANA (APY)", None, "other"),
        ("NPS TRUST A/C-SBI PENSION FUND SCHEME TAX SAVER TIER II", "II", "other"),
        ("TATA PENSION MANAGEMENT LIMITED TAX SAVER - TIER II", "II", "other"),
        ("NPS TRUST - A/C SBI PENSION FUND SCHEME - NPS TIER - II COMPOSITE SCHEME", "II", "other"),
        ("NPS TRUST A/C - ABSLPF SECURE FUTURE FUND - NPS - TIER I", "I", "other"),
        ("NPS TRUST A/C - UTI PF WEALTH BUILDER NPS EQUITY SCHEME - TIER II", "II", "other"),
        ("NPS TRUST - A/C SBI NPS SANCHAY SCHEME DIRECT", None, "other"),
    ],
)
def test_derive_tier_and_asset_class(name, tier, asset_class):
    assert nps.derive_tier(name) == tier
    assert nps.derive_asset_class(name) == asset_class
