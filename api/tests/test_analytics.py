"""Analytics maths: classification, allocation, concentration, liquidity. Pure; no DB.

Every expected figure is a hand-worked literal.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from app.services import analytics

TODAY = date(2026, 11, 2)

_LABELS = {
    "fd": "Fixed Deposits",
    "rd": "Recurring Deposits",
    "stock": "Stocks",
    "bond": "Bonds",
    "mf": "Mutual Funds",
    "nps": "NPS",
    "gold": "Gold & Silver",
    "cash": "Cash & Savings",
    "pf": "EPF & PPF",
    "other": "Other",
}


def h(asset_type, id_, value, status="active", **extra):
    """One valued holding (item) with just the fields the maths reads."""
    item = {"id": id_, "current_value": value, "status": status}
    if asset_type in ("fd", "rd"):
        item["bank"] = f"Bank {id_}"
    elif asset_type in ("mf", "nps"):
        item["scheme_name"] = f"Scheme {id_}"
    else:
        item["name"] = f"{asset_type} {id_}"
    item.update(extra)
    return asset_type, item


def groups_of(*holdings):
    """Groups in the build_groups shape, from (type, item) pairs."""
    by_type = {}
    for asset_type, item in holdings:
        by_type.setdefault(asset_type, []).append(item)
    return [
        {"type": t, "label": _LABELS[t], "items": items} for t, items in by_type.items()
    ]


def stock_master(kind="stock", name="X Ltd"):
    return {"kind": kind, "name": name}


def fund(amfi_category, name="Some Fund", amc="Some AMC"):
    return {"amfi_category": amfi_category, "name": name, "amc": amc}


# --- Empty and matured ---------------------------------------------------------------------------


def test_empty_portfolio_returns_zeros_and_empty_lists():
    for groups in ([], [{"type": "fd", "label": "Fixed Deposits", "items": []}]):
        alloc = analytics.allocation(groups)
        assert alloc["including_retirement"] == {"total": D("0.00"), "classes": []}
        assert alloc["excluding_retirement"] == {"total": D("0.00"), "classes": []}
        assert alloc["retirement_value"] == D("0.00")
        assert alloc["retirement_percent"] == D("0.00")

        conc = analytics.concentration(groups)
        assert conc["total"] == D("0.00")
        assert conc["top_holdings"] == []
        assert conc["flags"] == []
        assert [r["bars"] for r in conc["rollups"]] == [[], [], [], [], []]

        liq = analytics.liquidity(groups, today=TODAY)
        assert liq["total"] == D("0.00")
        assert [b["key"] for b in liq["buckets"]] == [
            "instant", "days", "breakable", "illiquid", "locked", "not_classified"
        ]  # fmt: skip
        assert all(b["amount"] == D("0.00") and b["percent"] == D("0.00") for b in liq["buckets"])


def test_matured_holdings_count_nowhere():
    groups = groups_of(
        h("fd", 1, 1000.0),
        h("fd", 2, 5000.0, status="matured"),
        h("cash", 3, 200.0),
        h("cash", 4, 900.0, status="matured"),
    )
    alloc = analytics.allocation(groups)
    assert alloc["including_retirement"]["total"] == D("1200.00")
    assert [c["class"] for c in alloc["including_retirement"]["classes"]] == ["debt", "cash"]
    conc = analytics.concentration(groups)
    assert conc["total"] == D("1200.00")
    assert [t["id"] for t in conc["top_holdings"]] == [1, 3]
    liq = analytics.liquidity(groups, today=TODAY)
    assert liq["total"] == D("1200.00")
    amounts = {b["key"]: b["amount"] for b in liq["buckets"]}
    assert amounts["breakable"] == D("1000.00")
    assert amounts["instant"] == D("200.00")


# --- Classification: stocks and ETFs -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Nippon India ETF Gold BeES", "gold"),
        ("Nippon India Silver ETF", "gold"),
        ("GOLDBEES", "gold"),
        ("Nippon India ETF Liquid BeES", "debt"),
        ("Bharat Bond ETF - April 2030", "debt"),
        ("BHARATBOND", "debt"),
        ("ICICI Prudential Gilt ETF", "debt"),
        ("Nippon India Nifty SDL Apr 2026 ETF", "debt"),  # SDL is checked before NIFTY
        ("Nippon India ETF Nifty 50 BeES", "equity"),
        ("HDFC BSE Sensex ETF", "equity"),
        ("Mirae Asset NYSE FANG+ ETF", "equity"),  # other ETFs are equity
    ],
)
def test_etf_name_rules(name, expected):
    item = {"master_id": 1, "name": name}
    assert analytics.classify_holding("stock", item, stock_masters={1: stock_master("etf", name)}) == expected


def test_etf_rule_order_gold_before_liquid_before_debt_before_equity():
    def etf(name):
        return analytics.classify_holding(
            "stock", {"master_id": 1}, stock_masters={1: stock_master("etf", name)}
        )

    assert etf("Gold Liquid ETF") == "gold"
    assert etf("Nifty Liquid ETF") == "debt"
    assert etf("Nifty Gilt ETF") == "debt"


@pytest.mark.parametrize("name", ["Gold Corp Ltd", "Silver Oak Industries", "Goldiam International"])
def test_non_etf_stock_with_gold_in_name_stays_equity(name):
    item = {"master_id": 1, "name": name}
    assert analytics.classify_holding("stock", item, stock_masters={1: stock_master("stock", name)}) == "equity"


def test_stock_without_master_is_equity():
    assert analytics.classify_holding("stock", {"master_id": None, "name": "Gold ETF"}) == "equity"
    assert analytics.classify_holding("stock", {"master_id": 99, "name": "x"}, stock_masters={}) == "equity"


def test_etf_token_matching_is_whole_word():
    # "GOLDEN" and "BONDI" are not the GOLD / BOND tokens.
    for name in ("Golden Nifty ETF", "Bondi Nifty ETF"):
        item = {"master_id": 1}
        assert analytics.classify_holding("stock", item, stock_masters={1: stock_master("etf", name)}) == "equity"


# --- Classification: mutual funds ----------------------------------------------------------------


def _mf(amfi_category, name="Some Fund", **item):
    item = {"scheme_code": 1, "scheme_name": name, "category": "other", **item}
    return analytics.classify_holding("mf", item, mf_masters={1: fund(amfi_category, name)})


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("Equity Scheme - Large Cap Fund", "equity"),
        ("Equity Schemes - Flexi Cap Fund", "equity"),
        ("Equity Schemes - ELSS- Tax Saver Fund", "equity"),
        ("Close Ended - Equity Scheme - ELSS", "equity"),
        ("Debt Scheme - Corporate Bond Fund", "debt"),
        ("Debt Scheme - Liquid Fund", "debt"),
        ("Debt Scheme - Money Market Fund", "debt"),
        ("Income/Debt Oriented Schemes - Ultra Short Term Fund", "debt"),
        ("Hybrid Scheme - Arbitrage Fund", "debt"),
        ("Hybrid Scheme - Aggressive Hybrid Fund", "hybrid"),
        ("Hybrid Scheme - Balanced Advantage Fund", "hybrid"),
        ("Hybrid Scheme - Conservative Hybrid Fund", "hybrid"),
        ("Hybrid Scheme - Multi Asset Allocation", "hybrid"),
        ("Other Scheme - Gold ETF", "gold"),
        ("Other Scheme - FoF Overseas", "equity"),
    ],
)
def test_mf_amfi_category_rules(category, expected):
    assert _mf(category) == expected


@pytest.mark.parametrize(
    ("category", "name", "expected"),
    [
        ("Other Scheme - Index Funds", "UTI Nifty 50 Index Fund", "equity"),
        ("Other Scheme - Index Funds", "Navi Nifty Next 50 Index Fund", "equity"),
        ("Other Scheme - Index Funds", "Some Total Market Index Fund", "equity"),
        ("Other Scheme - Index Funds", "Nippon India Nifty SDL Jun 2028 Index Fund", "debt"),
        ("Other Scheme - Index Funds", "Axis Nifty G-Sec Jul 2031 Index Fund", "debt"),
        ("Other Scheme - Index Funds", "Edelweiss Nifty PSU Bond Plus SDL Apr 2027 Index Fund", "debt"),
        ("Other Scheme - Index Funds", "ICICI Prudential Nifty Gilt Index Fund", "debt"),
        ("Other Scheme - Index Funds", "Some Target Maturity Index Fund 2030", "debt"),
        ("Other Scheme - Other ETFs", "Bharat Bond ETF - April 2031", "debt"),
        ("Other Scheme - Other ETFs", "Nippon India ETF Nifty BeES", "equity"),
        ("Other Scheme - Other ETFs", "Nippon India Silver ETF", "gold"),
        ("Other Scheme - FoF Domestic", "Axis Silver ETF Fund of Fund", "gold"),
        ("Other Scheme - FoF Domestic", "Bharat Bond FoF - April 2025", "debt"),
        ("Other Scheme - FoF Domestic", "Some Liquid ETF FoF", "debt"),
        ("Other Scheme - FoF Domestic", "Some Fund of Funds", "equity"),
    ],
)
def test_mf_index_etf_and_fof_follow_name_rules(category, name, expected):
    assert _mf(category, name) == expected


def test_mf_without_scheme_or_category_uses_name_rules_then_own_category_then_other():
    def classify(name, category="other", fund_row=None):
        item = {"scheme_code": 1 if fund_row else None, "scheme_name": name, "category": category}
        masters = {1: fund_row} if fund_row else {}
        return analytics.classify_holding("mf", item, mf_masters=masters)

    assert classify("Quant Gold Savings Fund") == "gold"
    assert classify("Nifty 50 Index Fund") == "equity"
    assert classify("Target Maturity Bond Fund") == "debt"
    assert classify("Mystery Fund") == "other"
    assert classify("Mystery Fund", "equity") == "equity"
    assert classify("Mystery Fund", "elss") == "equity"
    assert classify("Mystery Fund", "debt") == "debt"
    assert classify("Mystery Fund", "liquid") == "debt"
    assert classify("Mystery Fund", "hybrid") == "hybrid"
    # A linked scheme with no category, or one with no rule, behaves the same way.
    assert classify("Mystery Fund", fund_row=fund(None, "Mystery Fund")) == "other"
    retirement = fund("Solution Oriented Scheme - Retirement Fund", "Mystery Fund")
    assert classify("Mystery Fund", fund_row=retirement) == "other"
    assert classify("Mystery Fund", "hybrid", fund_row=retirement) == "hybrid"


def test_mf_missing_everything_does_not_crash():
    assert analytics.classify_holding("mf", {}) == "other"
    assert analytics.classify_holding("mf", {"scheme_code": 5, "scheme_name": None}, mf_masters={5: None}) == "other"


# --- Classification: everything else -------------------------------------------------------------


def test_bond_fd_rd_pf_cash_gold_other_classes():
    assert analytics.classify_holding("bond", {"bond_type": "corporate"}) == "debt"
    assert analytics.classify_holding("bond", {"bond_type": "government"}) == "debt"
    assert analytics.classify_holding("bond", {"bond_type": "sgb"}) == "gold"
    # The linked master can say SGB even when the entered type does not.
    assert (
        analytics.classify_holding(
            "bond", {"bond_type": "other", "master_id": 4}, bond_masters={4: {"bond_type": "sgb"}}
        )
        == "gold"
    )
    for asset_type in ("fd", "rd", "pf"):
        assert analytics.classify_holding(asset_type, {}) == "debt"
    assert analytics.classify_holding("cash", {}) == "cash"
    assert analytics.classify_holding("gold", {"metal": "silver"}) == "gold"
    assert analytics.classify_holding("gold", {"metal": "gold"}) == "gold"
    assert analytics.classify_holding("other", {}) == "other"


@pytest.mark.parametrize(
    ("asset_class", "expected"),
    [("E", "equity"), ("C", "debt"), ("G", "debt"), ("A", "debt"), ("other", "other"), (None, "other")],
)
def test_nps_asset_class(asset_class, expected):
    assert analytics.classify_holding("nps", {"asset_class": asset_class}) == expected


def test_retirement_money():
    for kind in ("epf", "vpf", "ppf"):
        assert analytics.is_retirement("pf", {"kind": kind})
    assert analytics.is_retirement("nps", {"tier": "I"})
    assert not analytics.is_retirement("nps", {"tier": "II"})
    assert analytics.is_retirement("nps", {"tier": None})  # unknown tier counts as Tier I
    for asset_type in ("fd", "rd", "stock", "bond", "mf", "gold", "cash", "other"):
        assert not analytics.is_retirement(asset_type, {})


# --- Allocation ----------------------------------------------------------------------------------


def _mixed_portfolio():
    return groups_of(
        h("stock", 1, 1000.10, master_id=1),
        h("mf", 2, 2000.20, scheme_code=10, category="equity"),
        h("mf", 3, 500.05, scheme_code=11, category="hybrid"),
        h("fd", 4, 3000.30),
        h("gold", 5, 750.07, metal="gold", form="bar"),
        h("cash", 6, 100.01),
        h("other", 7, 49.99),
        h("pf", 8, 4000.40, kind="epf"),
        h("nps", 9, 600.06, tier="I", asset_class="E"),
        h("nps", 10, 200.02, tier="II", asset_class="C"),
    )


_MIXED_MASTERS = {
    "stock_masters": {1: stock_master()},
    "mf_masters": {
        10: fund("Equity Scheme - Large Cap Fund"),
        11: fund("Hybrid Scheme - Aggressive Hybrid Fund"),
    },
}


def test_allocation_including_and_excluding_retirement():
    alloc = analytics.allocation(_mixed_portfolio(), **_MIXED_MASTERS)

    inc = alloc["including_retirement"]
    assert inc["total"] == D("12201.20")
    assert [(c["class"], c["value"], c["percent"]) for c in inc["classes"]] == [
        ("equity", D("3600.36"), D("29.51")),
        ("debt", D("7200.72"), D("59.02")),
        ("hybrid", D("500.05"), D("4.10")),
        ("gold", D("750.07"), D("6.15")),
        ("cash", D("100.01"), D("0.82")),
        ("other", D("49.99"), D("0.41")),
    ]

    exc = alloc["excluding_retirement"]
    assert exc["total"] == D("7600.74")
    assert [(c["class"], c["value"], c["percent"]) for c in exc["classes"]] == [
        ("equity", D("3000.30"), D("39.47")),
        ("debt", D("3200.32"), D("42.11")),
        ("hybrid", D("500.05"), D("6.58")),
        ("gold", D("750.07"), D("9.87")),
        ("cash", D("100.01"), D("1.32")),
        ("other", D("49.99"), D("0.66")),
    ]
    assert alloc["retirement_value"] == D("4600.46")
    assert alloc["retirement_percent"] == D("37.70")


def test_allocation_drill_down_class_to_type_to_holdings():
    alloc = analytics.allocation(_mixed_portfolio(), **_MIXED_MASTERS)
    equity = alloc["including_retirement"]["classes"][0]
    assert equity["label"] == "Equity"
    assert [(t["type"], t["label"], t["value"], t["percent"]) for t in equity["types"]] == [
        ("mf", "Mutual Funds", D("2000.20"), D("16.39")),
        ("stock", "Stocks", D("1000.10"), D("8.20")),
        ("nps", "NPS", D("600.06"), D("4.92")),
    ]
    assert equity["types"][2]["holdings"] == [
        {"id": 9, "name": "Scheme 9", "value": D("600.06"), "percent": D("4.92")}
    ]
    debt = alloc["including_retirement"]["classes"][1]
    # EPF 4000.40 > FD 3000.30 > NPS Tier II (debt) 200.02
    assert [t["type"] for t in debt["types"]] == ["pf", "fd", "nps"]
    assert debt["types"][1]["holdings"][0]["name"] == "Bank 4"
    # Retirement off drops the EPF and NPS Tier I rows from the drill-down too.
    debt_x = alloc["excluding_retirement"]["classes"][1]
    assert [t["type"] for t in debt_x["types"]] == ["fd", "nps"]
    equity_x = alloc["excluding_retirement"]["classes"][0]
    assert [t["type"] for t in equity_x["types"]] == ["mf", "stock"]


def test_allocation_class_totals_reconcile_with_active_holdings_exactly():
    # Floats whose binary sum is not exact: 0.1 + 0.2 must be exactly 0.30.
    groups = groups_of(
        h("cash", 1, 0.1),
        h("cash", 2, 0.2),
        h("fd", 3, 33.33),
        h("fd", 4, 66.67),
        h("fd", 5, 1.0, status="matured"),
    )
    view = analytics.allocation(groups)["including_retirement"]
    by_class = {c["class"]: c["value"] for c in view["classes"]}
    assert by_class == {"debt": D("100.00"), "cash": D("0.30")}
    assert view["total"] == D("100.30")
    assert sum(by_class.values()) == view["total"]
    cash = view["classes"][1]["types"][0]["holdings"]
    assert [x["value"] for x in cash] == [D("0.20"), D("0.10")]


def test_allocation_sums_unrounded_and_rounds_only_the_total():
    # Three holdings of 0.004 each round to 0.00 on their own but the class holds 0.012 -> 0.01.
    groups = groups_of(h("cash", 1, 0.004), h("cash", 2, 0.004), h("cash", 3, 0.004))
    cash = analytics.allocation(groups)["including_retirement"]["classes"][0]
    assert cash["value"] == D("0.01")
    assert [x["value"] for x in cash["types"][0]["holdings"]] == [D("0.00")] * 3
    # HALF_UP on 0.005: 10.005 -> 10.01.
    groups = groups_of(h("cash", 1, 10.005))
    assert analytics.allocation(groups)["including_retirement"]["total"] == D("10.01")


def test_allocation_omits_classes_with_no_value_and_handles_zero_total():
    groups = groups_of(h("cash", 1, 0.0), h("fd", 2, 500.0))
    view = analytics.allocation(groups)["including_retirement"]
    assert [c["class"] for c in view["classes"]] == ["debt"]
    only_retirement = groups_of(h("pf", 1, 100.0, kind="ppf"))
    alloc = analytics.allocation(only_retirement)
    assert alloc["excluding_retirement"] == {"total": D("0.00"), "classes": []}
    assert alloc["retirement_percent"] == D("100.00")


def test_allocation_sgb_is_gold_and_nps_tiers():
    groups = groups_of(
        h("bond", 1, 4800.0, bond_type="sgb"),
        h("bond", 2, 1000.0, bond_type="corporate"),
        h("nps", 3, 300.0, tier="I", asset_class="E"),
        h("nps", 4, 200.0, tier="II", asset_class="G"),
    )
    alloc = analytics.allocation(groups)
    classes = {c["class"]: c["value"] for c in alloc["including_retirement"]["classes"]}
    assert classes == {"equity": D("300.00"), "debt": D("1200.00"), "gold": D("4800.00")}
    classes_x = {c["class"]: c["value"] for c in alloc["excluding_retirement"]["classes"]}
    assert classes_x == {"debt": D("1200.00"), "gold": D("4800.00")}  # Tier I equity is out, Tier II in


# --- Bank resolution -----------------------------------------------------------------------------


def test_resolve_bank_follows_merge_chain_to_survivor():
    issuers = {
        1: {"name": "Syndicate Bank", "merged_into_id": 2},
        2: {"name": "Mid Bank", "merged_into_id": 3},
        3: {"name": "Canara Bank", "short_name": "Canara", "merged_into_id": None},
    }
    for issuer_id in (1, 2, 3):
        bank = analytics.resolve_bank({"issuer_id": issuer_id, "bank": "typed"}, issuers)
        assert bank == analytics.Bank("issuer:3", "Canara", 3)
    assert analytics.resolve_issuer_id(1, issuers) == 3


def test_resolve_bank_guards_against_cycles():
    issuers = {
        10: {"name": "A", "merged_into_id": 11},
        11: {"name": "B", "merged_into_id": 12},
        12: {"name": "C", "merged_into_id": 10},
        20: {"name": "Self", "merged_into_id": 20},
        # 30 feeds into the 10-11-12 loop from outside it.
        30: {"name": "Tail", "merged_into_id": 11},
    }
    for issuer_id in (10, 11, 12, 30):
        assert analytics.resolve_issuer_id(issuer_id, issuers) == 10  # smallest id in the loop
    assert analytics.resolve_issuer_id(20, issuers) == 20


def test_resolve_bank_stops_at_last_known_issuer_when_survivor_missing_from_lookup():
    issuers = {1: {"name": "Old", "merged_into_id": 99}}
    assert analytics.resolve_issuer_id(1, issuers) == 1
    assert analytics.resolve_issuer_id(5, issuers) is None


def test_resolve_bank_groups_manual_names_trimmed_and_case_insensitive():
    a = analytics.resolve_bank({"issuer_id": None, "bank": "  HDFC   Bank "})
    b = analytics.resolve_bank({"bank": "hdfc bank"})
    c = analytics.resolve_bank({"bank": "HDFC BANK", "issuer_id": 404}, {})  # unknown issuer id
    assert a == analytics.Bank("name:hdfc bank", "HDFC Bank", None)
    assert a.key == b.key == c.key
    assert analytics.resolve_bank({"bank": "   "}).name == "Unknown bank"


# --- Concentration -------------------------------------------------------------------------------


def test_top_holdings_cut_off_at_ten_with_percent_of_total():
    groups = groups_of(*[h("stock", i, i * 100.0) for i in range(1, 13)])  # 100 .. 1200
    top = analytics.concentration(groups)["top_holdings"]
    assert len(top) == 10
    assert [t["id"] for t in top] == [12, 11, 10, 9, 8, 7, 6, 5, 4, 3]
    assert top[0] == {
        "type": "stock", "id": 12, "name": "stock 12", "value": D("1200.00"), "percent": D("15.38")
    }  # fmt: skip
    assert top[-1]["percent"] == D("3.85")  # 300 of 7800


def test_top_holdings_tie_break_is_type_then_id():
    groups = groups_of(
        h("stock", 2, 500.0),
        h("stock", 1, 500.0),
        h("fd", 9, 500.0),
        h("cash", 1, 500.0),
        h("pf", 3, 900.0, kind="epf"),
    )
    top = analytics.concentration(groups)["top_holdings"]
    assert [(t["type"], t["id"]) for t in top] == [
        ("pf", 3), ("cash", 1), ("fd", 9), ("stock", 1), ("stock", 2)
    ]  # fmt: skip


def test_top_holdings_include_retirement_money():
    groups = groups_of(h("pf", 1, 300.0, kind="epf"), h("cash", 2, 100.0))
    top = analytics.concentration(groups)["top_holdings"]
    assert [t["percent"] for t in top] == [D("75.00"), D("25.00")]


def test_rollups_by_company_amc_bank_issuer_and_pfm():
    groups = groups_of(
        h("stock", 1, 600.0, master_id=1),
        h("stock", 2, 400.0, master_id=1),
        h("stock", 3, 1000.0, master_id=2),
        h("stock", 4, 100.0, master_id=None, name="  Manual Co "),
        h("stock", 5, 100.0, master_id=None, name="manual co"),
        h("mf", 6, 300.0, scheme_code=10),
        h("mf", 7, 400.0, scheme_code=10),
        h("mf", 8, 200.0, scheme_code=11),
        h("mf", 9, 100.0, scheme_code=None),
        h("fd", 10, 600.0, issuer_id=1, bank="Syndicate"),
        h("rd", 11, 200.0, issuer_id=3, bank="Canara"),
        h("fd", 12, 200.0, issuer_id=None, bank="Axis Bank"),
        h("bond", 13, 600.0, master_id=None, issuer="NHAI"),
        h("bond", 14, 200.0, master_id=None, issuer="nhai "),
        h("bond", 15, 200.0, master_id=None, issuer="REC"),
        h("nps", 16, 300.0, pfm_name="SBI Pension Funds", tier="I", asset_class="E"),
        h("nps", 17, 100.0, pfm_name="sbi pension funds", tier="I", asset_class="C"),
    )
    conc = analytics.concentration(
        groups,
        stock_masters={
            1: stock_master("stock", "Reliance Industries Ltd"),
            2: stock_master("etf", "Nippon India ETF Nifty BeES"),
        },
        mf_masters={10: fund("x", amc="HDFC Mutual Fund"), 11: fund("x", amc="SBI Mutual Fund")},
        issuer_masters={
            1: {"name": "Syndicate Bank", "merged_into_id": 3},
            3: {"name": "Canara Bank", "short_name": "Canara", "merged_into_id": None},
        },
    )
    rollups = {r["key"]: r for r in conc["rollups"]}
    assert [r["key"] for r in conc["rollups"]] == ["stock", "mf_amc", "bank", "bond_issuer", "nps_pfm"]

    def bars(key):
        return [(b["label"], b["value"], b["percent"], b["passive"]) for b in rollups[key]["bars"]]

    assert rollups["stock"]["total"] == D("2200.00")
    assert bars("stock") == [
        ("Nippon India ETF Nifty BeES", D("1000.00"), D("45.45"), True),
        ("Reliance Industries Ltd", D("1000.00"), D("45.45"), False),
        ("Manual Co", D("200.00"), D("9.09"), False),
    ]
    assert bars("mf_amc") == [
        ("HDFC Mutual Fund", D("700.00"), D("70.00"), False),
        ("SBI Mutual Fund", D("200.00"), D("20.00"), False),
        ("Unknown AMC", D("100.00"), D("10.00"), False),
    ]
    assert bars("bank") == [
        ("Canara", D("800.00"), D("80.00"), False),
        ("Axis Bank", D("200.00"), D("20.00"), False),
    ]
    assert bars("bond_issuer") == [
        ("NHAI", D("800.00"), D("80.00"), False),
        ("REC", D("200.00"), D("20.00"), False),
    ]
    assert bars("nps_pfm") == [("SBI Pension Funds", D("400.00"), D("100.00"), False)]


@pytest.mark.parametrize(
    ("stock_value", "etf_value", "flagged", "percent"),
    [
        (100.0, 900.0, False, None),  # exactly 10% of equity 1000
        (100.01, 899.99, True, D("10.00")),  # 10.001% -> shown as 10.00, still strictly over
        (101.0, 899.0, True, D("10.10")),
        (99.99, 900.01, False, None),
    ],
)
def test_single_stock_flag_threshold_and_etf_never_flagged(stock_value, etf_value, flagged, percent):
    groups = groups_of(
        h("stock", 1, stock_value, master_id=1),
        h("stock", 2, etf_value, master_id=2),  # 90% of equity, but an ETF
    )
    conc = analytics.concentration(
        groups,
        stock_masters={1: stock_master("stock", "Acme Ltd"), 2: stock_master("etf", "Nifty BeES")},
    )
    flags = [f for f in conc["flags"] if f["kind"] == "single_stock"]
    if flagged:
        assert [(f["label"], f["percent"], f["threshold"]) for f in flags] == [
            ("Acme Ltd", percent, D(10))
        ]
    else:
        assert flags == []


def test_single_stock_flag_uses_whole_equity_class_including_funds_and_retirement():
    # Equity class = stock 100 + equity MF 400 + NPS Tier I equity 500 = 1000, so 10% exactly.
    groups = groups_of(
        h("stock", 1, 100.0, master_id=1),
        h("mf", 2, 400.0, scheme_code=10),
        h("nps", 3, 500.0, tier="I", asset_class="E", pfm_name="P"),
        h("fd", 4, 9000.0),  # debt, not in the denominator
    )
    masters = {
        "stock_masters": {1: stock_master("stock", "Acme Ltd")},
        "mf_masters": {10: fund("Equity Scheme - Large Cap Fund")},
    }
    flags = analytics.concentration(groups, **masters)["flags"]
    assert [f for f in flags if f["kind"] == "single_stock"] == []  # exactly 10%: no flag
    bigger = groups_of(
        h("stock", 1, 100.01, master_id=1),
        h("mf", 2, 399.99, scheme_code=10),
        h("nps", 3, 500.0, tier="I", asset_class="E", pfm_name="P"),
    )
    flags = analytics.concentration(bigger, **masters)["flags"]
    assert [(f["kind"], f["label"], f["value"]) for f in flags if f["kind"] == "single_stock"] == [
        ("single_stock", "Acme Ltd", D("100.01"))
    ]


def test_single_stock_flag_rolls_up_lots_of_one_company():
    groups = groups_of(
        h("stock", 1, 60.0, master_id=1),
        h("stock", 2, 60.0, master_id=1),
        h("stock", 3, 880.0, master_id=2),
    )
    conc = analytics.concentration(
        groups,
        stock_masters={1: stock_master("stock", "Acme Ltd"), 2: stock_master("stock", "Big Ltd")},
    )
    # Acme is 120 of 1000 (two 6% lots add up); Big at 88% is flagged too.
    assert [(f["label"], f["percent"]) for f in conc["flags"]] == [
        ("Big Ltd", D("88.00")),
        ("Acme Ltd", D("12.00")),
    ]


def test_index_funds_never_get_the_single_stock_flag():
    groups = groups_of(h("mf", 1, 1000.0, scheme_code=10))
    conc = analytics.concentration(
        groups, mf_masters={10: fund("Other Scheme - Index Funds", "UTI Nifty 50 Index Fund")}
    )
    assert [f for f in conc["flags"] if f["kind"] == "single_stock"] == []


def test_amc_flag_threshold_exactly_30_and_just_above():
    def run(values):
        groups = groups_of(*[h("mf", i, v, scheme_code=i) for i, v in enumerate(values, 1)])
        masters = {i: fund("x", amc=f"AMC {i}") for i in range(1, len(values) + 1)}
        return analytics.concentration(groups, mf_masters=masters)["flags"]

    assert run([3000.0, 3000.0, 2000.0, 2000.0]) == []  # exactly 30% each: not flagged
    flags = run([3001.0, 2999.0, 2000.0, 2000.0])
    assert [(f["kind"], f["label"], f["value"], f["percent"], f["threshold"]) for f in flags] == [
        ("amc", "AMC 1", D("3001.00"), D("30.01"), D(30))
    ]
    assert run([6000.0, 4000.0])[0]["percent"] == D("60.00")


def test_amc_flag_ignores_non_mf_money():
    groups = groups_of(h("mf", 1, 100.0, scheme_code=1), h("fd", 2, 10000.0))
    conc = analytics.concentration(groups, mf_masters={1: fund("x", amc="Only AMC")})
    assert [(f["label"], f["percent"]) for f in conc["flags"]] == [("Only AMC", D("100.00"))]


def test_no_cross_asset_company_rollup():
    groups = groups_of(
        h("stock", 1, 100.0, master_id=1),
        h("bond", 2, 100.0, master_id=None, issuer="Bajaj Finance"),
        h("fd", 3, 100.0, bank="Bajaj Finance"),
    )
    conc = analytics.concentration(
        groups, stock_masters={1: stock_master("stock", "Bajaj Finance")}
    )
    labels = [(r["key"], [b["label"] for b in r["bars"]]) for r in conc["rollups"]]
    assert labels[0] == ("stock", ["Bajaj Finance"])
    assert labels[2] == ("bank", ["Bajaj Finance"])
    assert labels[3] == ("bond_issuer", ["Bajaj Finance"])
    assert all(r["total"] == D("100.00") for r in (conc["rollups"][0], conc["rollups"][2], conc["rollups"][3]))


# --- Liquidity -----------------------------------------------------------------------------------


def _by_key(result):
    return {b["key"]: (b["amount"], b["percent"]) for b in result["buckets"]}


def test_liquidity_buckets_per_asset_type():
    groups = groups_of(
        h("cash", 1, 100.0),
        h("stock", 2, 200.0),
        h("mf", 3, 300.0, scheme_code=10, category="liquid"),
        h("gold", 4, 50.0, form="digital"),
        h("gold", 5, 70.0, form="bar"),
        h("gold", 6, 30.0, form="jewellery", metal="silver"),
        h("nps", 7, 40.0, tier="II", asset_class="E"),
        h("nps", 8, 60.0, tier="I", asset_class="E"),
        h("pf", 9, 500.0, kind="ppf"),
        h("fd", 10, 1000.0),
        h("rd", 11, 250.0),
        h("bond", 12, 400.0, bond_type="corporate"),
        h("bond", 13, 80.0, bond_type="sgb"),
        h("other", 14, 25.0),
        h("fd", 15, 999.0, status="matured"),
    )
    result = analytics.liquidity(
        groups, today=TODAY, mf_masters={10: fund("Debt Scheme - Liquid Fund")}
    )
    assert result["total"] == D("3105.00")
    assert [b["key"] for b in result["buckets"]] == [
        "instant", "days", "breakable", "illiquid", "locked", "not_classified"
    ]  # fmt: skip
    # days = 200 + 300 + 50 + 40; illiquid = 70 + 30 + 400 + 80; locked = 60 + 500.
    assert _by_key(result) == {
        "instant": (D("100.00"), D("3.22")),
        "days": (D("590.00"), D("19.00")),
        "breakable": (D("1250.00"), D("40.26")),
        "illiquid": (D("580.00"), D("18.68")),
        "locked": (D("560.00"), D("18.04")),
        "not_classified": (D("25.00"), D("0.81")),
    }


def test_liquidity_includes_retirement_and_non_elss_equity_funds_are_days():
    groups = groups_of(
        h("mf", 1, 400.0, scheme_code=10, category="equity"),
        h("pf", 2, 600.0, kind="epf"),
    )
    result = analytics.liquidity(
        groups, today=TODAY, mf_masters={10: fund("Equity Scheme - Large Cap Fund")}
    )
    assert _by_key(result)["days"] == (D("400.00"), D("40.00"))
    assert _by_key(result)["locked"] == (D("600.00"), D("60.00"))


def _txn(when, kind, units):
    return {"txn_date": when, "kind": kind, "units": units}


ELSS = {10: fund("Equity Schemes - ELSS- Tax Saver Fund")}


def test_elss_fifo_split_by_remaining_units():
    # Lots: 200 units (2023-01-01, past the lock), 100 (2024-01-15) and 100 (2025-06-01), both
    # still locked. FIFO redemption of 50 units trims the oldest lot to 150: 150 free, 200 locked.
    txns = {
        7: [
            _txn("2024-01-15", "purchase", 100),
            _txn("2023-01-01", "purchase", 200),
            _txn("2025-12-01", "redemption", 50),
            _txn("2025-06-01", "purchase", 100),
        ]
    }
    groups = groups_of(h("mf", 7, 1000.0, scheme_code=10, category="elss", purchase_date="2023-01-01"))
    result = analytics.liquidity(groups, today=TODAY, mf_masters=ELSS, mf_transactions=txns)
    # locked = 1000 * 200 / 350 = 571.43 (571.428...), free = 428.57.
    assert _by_key(result)["locked"] == (D("571.43"), D("57.14"))
    assert _by_key(result)["days"] == (D("428.57"), D("42.86"))
    assert result["total"] == D("1000.00")


def test_elss_redemptions_come_off_the_oldest_lots_first():
    # Same lots, 150 units redeemed: FIFO leaves 50 free + 200 locked, so 80% locked.
    # (LIFO would leave 200 free + 50 locked, i.e. 20% locked.)
    lots = [
        _txn("2023-01-01", "purchase", 200),
        _txn("2024-01-15", "purchase", 100),
        _txn("2025-06-01", "purchase", 100),
    ]
    locked, free = analytics.elss_split(
        D("1000.00"), None, [*lots, _txn("2025-12-01", "redemption", 150)], TODAY
    )
    assert (locked, free) == (D("800.00"), D("200.00"))
    # 250 units redeemed: the oldest lot is gone and 50 of the next; all that is left is locked.
    locked, free = analytics.elss_split(
        D("1000.00"), None, [*lots, _txn("2025-12-01", "redemption", 250)], TODAY
    )
    assert (locked, free) == (D("1000.00"), D("0"))


def test_elss_lock_boundary_is_exactly_three_years():
    def split(when):
        return analytics.elss_split(D("100.00"), None, [_txn(when, "purchase", 10)], TODAY)

    assert split("2023-11-02") == (D("0.00"), D("100.00"))  # exactly 3 years ago: unlocked
    assert split(date(2023, 11, 2)) == (D("0.00"), D("100.00"))
    assert split("2023-11-03") == (D("100.00"), D("0"))  # a day short: locked
    assert split("2026-11-02") == (D("100.00"), D("0"))  # bought today

    # The same cut-off applies to a fund with no transactions (purchase date only).
    assert analytics.elss_split(D("100.00"), "2023-11-02", None, TODAY) == (D("0"), D("100.00"))
    assert analytics.elss_split(D("100.00"), "2023-11-03", [], TODAY) == (D("100.00"), D("0"))


def test_elss_without_transactions_uses_purchase_date():
    groups = groups_of(
        h("mf", 1, 300.0, scheme_code=10, purchase_date="2024-05-01"),  # locked until 2027-05-01
        h("mf", 2, 200.0, scheme_code=10, purchase_date="2020-01-01"),
    )
    result = analytics.liquidity(groups, today=TODAY, mf_masters=ELSS)
    assert _by_key(result)["locked"] == (D("300.00"), D("60.00"))
    assert _by_key(result)["days"] == (D("200.00"), D("40.00"))


def test_elss_with_no_date_at_all_is_locked():
    groups = groups_of(
        h("mf", 1, 300.0, scheme_code=10, purchase_date=None),
        h("mf", 2, 100.0, scheme_code=10),
        h("mf", 3, 100.0, scheme_code=10, purchase_date="not a date"),
    )
    result = analytics.liquidity(groups, today=TODAY, mf_masters=ELSS, mf_transactions={1: []})
    assert _by_key(result)["locked"] == (D("500.00"), D("100.00"))
    assert _by_key(result)["days"] == (D("0.00"), D("0.00"))


def test_elss_fully_redeemed_lots_fall_back_to_purchase_date():
    txns = {
        1: [_txn("2025-01-01", "purchase", 10), _txn("2025-06-01", "redemption", 10)],
    }
    groups = groups_of(h("mf", 1, 100.0, scheme_code=10, purchase_date="2020-01-01"))
    result = analytics.liquidity(groups, today=TODAY, mf_masters=ELSS, mf_transactions=txns)
    assert _by_key(result)["days"] == (D("100.00"), D("100.00"))


def test_elss_same_day_purchase_is_applied_before_redemption():
    txns = [_txn("2025-03-01", "redemption", 10), _txn("2025-03-01", "purchase", 10)]
    # Listed redemption-first, but the purchase counts first, so nothing is left: no lots, and
    # with no purchase date the fund falls back to locked.
    assert analytics.elss_split(D("50.00"), None, txns, TODAY) == (D("50.00"), D("0"))
    # With an old purchase date the fallback is free: proves the lots were fully consumed.
    assert analytics.elss_split(D("50.00"), "2019-01-01", txns, TODAY) == (D("0"), D("50.00"))


def test_elss_detected_by_scheme_category_or_own_category():
    groups = groups_of(
        h("mf", 1, 100.0, scheme_code=10, category="equity", purchase_date="2026-01-01"),  # linked ELSS
        h("mf", 2, 100.0, scheme_code=None, category="elss", purchase_date="2026-01-01"),  # manual ELSS
        h("mf", 3, 100.0, scheme_code=11, category="elss", purchase_date="2026-01-01"),  # linked, not ELSS
    )
    masters = {**ELSS, 11: fund("Equity Scheme - Flexi Cap Fund")}
    result = analytics.liquidity(groups, today=TODAY, mf_masters=masters)
    assert _by_key(result)["locked"][0] == D("200.00")
    assert _by_key(result)["days"][0] == D("100.00")


def test_liquidity_reconciles_with_active_total_after_elss_split():
    txns = {
        7: [
            _txn("2023-01-01", "purchase", 3),
            _txn("2025-01-01", "purchase", 4),
        ]
    }
    groups = groups_of(
        h("mf", 7, 1000.01, scheme_code=10, category="elss"),
        h("cash", 1, 0.1),
        h("cash", 2, 0.2),
        h("fd", 3, 33.33),
        h("fd", 4, 5.0, status="matured"),
    )
    result = analytics.liquidity(groups, today=TODAY, mf_masters=ELSS, mf_transactions=txns)
    # locked = 1000.01 * 4 / 7 = 571.43 (571.4342...); free = 1000.01 - 571.43 = 428.58.
    amounts = {b["key"]: b["amount"] for b in result["buckets"]}
    assert amounts == {
        "instant": D("0.30"),
        "days": D("428.58"),
        "breakable": D("33.33"),
        "illiquid": D("0.00"),
        "locked": D("571.43"),
        "not_classified": D("0.00"),
    }
    assert result["total"] == D("1033.64")
    assert sum(amounts.values()) == result["total"]
    assert [b["percent"] for b in result["buckets"]] == [
        D("0.03"), D("41.46"), D("3.22"), D("0.00"), D("55.28"), D("0.00")
    ]  # fmt: skip
