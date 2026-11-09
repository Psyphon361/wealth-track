"""The web's TypeScript types (web/lib/types.ts) must not name fields the API does not send.

Typed models: every field declared in a mapped TS interface must exist in the OpenAPI schema's
properties (TS may leave fields out; the API may add some).
Holding items: OpenAPI only types them as `list[dict[str, Any]]`, so the TS item types are checked
against the KEYS of real responses (GET /api/holdings/{type}, /{id}, /api/portfolio) for one seeded
holding per asset type (SQLite, no network).
"""

import json
import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import GoldRateHistory, NpsMaster, NpsNavLatest, StockPriceLatest
from tests.contract.update_snapshot import SNAPSHOT
from tests.test_exits_api import BOND, CASH, FD, GOLD, OTHER, RD, STOCK, add
from tests.test_scoping import client, users  # noqa: F401  (fixtures)
from tests.test_sip_api import HOLDING as FUND
from tests.test_sip_api import sc  # noqa: F401  (fixture: MF master, NAVs, today = 2026-03-10)

TYPES_TS = Path(__file__).resolve().parents[3] / "web" / "lib" / "types.ts"

# TS interface or type name -> OpenAPI schema name (typed models).
TS_TO_SCHEMA = {
    # request bodies
    "FixedDepositInput": "FixedDepositCreateIn",
    "RecurringDepositInput": "RecurringDepositCreateIn",
    "StockInput": "StockCreateIn",
    "BondInput": "BondCreateIn",
    "MutualFundInput": "MutualFundCreateIn",
    "GoldInput": "GoldCreateIn",
    "CashInput": "CashCreateIn",
    "OtherInput": "OtherCreateIn",
    "PfInput": "PfCreateIn",
    "NpsInput": "NpsCreateIn",
    "SipInput": "SipCreate",
    "SipUpdateInput": "SipUpdate",
    "CasCommitRow": "CasCommitRow",
    # masters and lookups
    "FdIssuer": "FdIssuerRead",
    "StockMaster": "StockMasterRead",
    "BondMaster": "BondMasterRead",
    "MfScheme": "MFSchemeRead",
    "MfNavResponse": "MFNavOnDate",
    "NpsScheme": "NpsMasterRead",
    "GoldRateResponse": "GoldRateOnDate",
    # CAS import
    "CasExistingHolding": "ExistingHolding",
    "CasTransaction": "CasTransaction-Output",
    "CasPreviewRow": "CasPreviewRow",
    "CasPreview": "CasPreview",
    "CasCommitResult": "CasCommitResult",
    # records, exits, dashboard, portfolio
    "RecordFields": "FixedDepositRead",
    "ExitSummary": "ExitRead",
    "UnsettledItem": "UnsettledItem",
    "Unsettled": "Unsettled",
    "Totals": "Totals",
    "PortfolioGroup": "PortfolioGroup",
    "PortfolioResponse": "PortfolioResponse",
    "DashboardByType": "DashboardByType",
    "DashboardResponse": "DashboardResponse",
    "FacetValue": "FacetValue",
    "HoldingsSummary": "HoldingsSummary",
    "HoldingsResponse": "HoldingsResponse",
    "HoldingDetailResponse": "HoldingDetailResponse",
    "NetWorthPoint": "NetWorthPoint",
    "NetWorthHistory": "NetWorthHistoryResponse",
    "DeletedHolding": "DeletedHolding",
    # analytics overview
    "AnalyticsAllocationHolding": "AllocationHolding",
    "AnalyticsAllocationType": "AllocationType",
    "AnalyticsAllocationClass": "AllocationClass",
    "AnalyticsAllocationView": "AllocationView",
    "AnalyticsAllocation": "AllocationSection",
    "AnalyticsMaturityRow": "MaturityRow",
    "AnalyticsMaturityWindow": "MaturityWindow",
    "AnalyticsMaturedHolding": "MaturedHolding",
    "AnalyticsComingUp": "ComingUpSection",
    "AnalyticsHealthItem": "HealthItem",
    "AnalyticsDataHealth": "DataHealthSection",
    "AnalyticsTopHolding": "TopHolding",
    "AnalyticsRollupBar": "RollupBar",
    "AnalyticsRollup": "Rollup",
    "AnalyticsConcentrationFlag": "ConcentrationFlag",
    "AnalyticsConcentrationOthers": "ConcentrationOthers",
    "AnalyticsConcentration": "ConcentrationSection",
    "AnalyticsLiquidityBucket": "LiquidityBucket",
    "AnalyticsLiquidity": "LiquiditySection",
    "AnalyticsBankHolding": "BankHolding",
    "AnalyticsBankRow": "BankRow",
    "AnalyticsBankSafety": "BankSafetySection",
    "AnalyticsOverview": "AnalyticsOverview",
    # analytics growth, returns, tax, bond schedule
    "AnalyticsGrowthPeriod": "GrowthPeriod",
    "AnalyticsGrowthMonth": "GrowthMonth",
    "AnalyticsGrowth": "AnalyticsGrowth",
    "ReturnGroup": "ReturnGroup",
    "RankedHolding": "RankedHolding",
    "ReferenceRate": "ReferenceRate",
    "ReturnsExcluded": "ReturnsExcluded",
    "BenchmarkPair": "BenchmarkComparison",
    "ReturnsBenchmark": "Benchmark",
    "AnalyticsReturns": "AnalyticsReturns",
    "TaxFyOption": "TaxFy",
    "TaxPayment": "TaxPayment",
    "TaxHolding": "TaxHolding",
    "TaxFreeItem": "TaxFreeItem",
    "TaxClassRow": "TaxByClass",
    "TaxPayer": "TaxPayer",
    "AnalyticsTax": "AnalyticsTax",
    "BondPayment": "BondPayment",
    "BondFyRow": "BondFySummary",
    "BondScheduleBond": "BondSchedule",
    "BondSchedule": "BondScheduleResponse",
    # SIPs and MF transactions
    "Sip": "SipRead",
    "SipResult": "SipResult",
    "MfTransaction": "SipTransaction",
    "MfTransactionsResponse": "SipTransactionsResponse",
}

# TS interface -> reason, for mismatches that already existed when this test was written. Each entry
# is {ts interface: {field: reason}}; the test fails if a listed drift is gone (remove the entry).
KNOWN_DRIFT: dict[str, dict[str, str]] = {}

# TS holding item type per asset slug (checked against real API responses).
ITEM_TYPES = {
    "fd": "FixedDepositItem",
    "rd": "RecurringDepositItem",
    "stock": "StockItem",
    "bond": "BondItem",
    "mf": "MutualFundItem",
    "gold": "GoldItem",
    "cash": "CashItem",
    "pf": "PfItem",
    "nps": "NpsItem",
    "other": "OtherItem",
}
# Documented fields a real response may legitimately lack although the TS type says required.
OPTIONAL: dict[str, set[str]] = {}


# --- a small TypeScript declaration parser ------------------------------------------------------


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _matching(text: str, start: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    raise ValueError("unbalanced braces in types.ts")


def parse_declarations(text: str) -> dict[str, str]:
    """name -> right-hand side (interface body wrapped in braces, or the type expression)."""
    text = _strip_comments(text)
    decls: dict[str, str] = {}
    for m in re.finditer(r"^export (interface|type) (\w+)(?:<[^{=]*>)?\s*(=)?\s*", text, re.M):
        kind, name = m.group(1), m.group(2)
        pos = m.end()
        if kind == "interface":
            end = _matching(text, text.index("{", m.start()), "{", "}")
            decls[name] = text[text.index("{", m.start()) : end + 1]
        else:
            end = pos
            depth = 0
            while end < len(text):
                ch = text[end]
                if ch in "{([":
                    depth += 1
                elif ch in "})]":
                    depth -= 1
                elif ch == "<" and text[end - 1] != "=":
                    depth += 1
                elif ch == ">" and text[end - 1] != "=":
                    depth -= 1
                elif ch == ";" and depth == 0:
                    break
                elif ch == "\n" and depth == 0:
                    rest = text[end:].lstrip()
                    if rest and rest[0] not in "|&":
                        # a type alias ends at a blank line / next declaration unless it continues
                        if not text[pos:end].rstrip().endswith(("=", "|", "&")):
                            break
                end += 1
            decls[name] = text[pos:end].strip()
    return decls


def _split_top(text: str, seps: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for i, ch in enumerate(text):
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        elif ch == "<" or (ch == ">" and text[i - 1] != "="):
            depth += 1 if ch == "<" else -1
        if depth == 0 and ch in seps:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def body_fields(body: str) -> dict[str, bool]:
    """field name -> optional?, for the top level of an object literal `{ ... }`."""
    inner = body.strip()[1:-1]
    fields: dict[str, bool] = {}
    for piece in _split_top(inner, ";\n,"):
        m = re.match(r"^(\w+)(\?)?\s*:", piece)
        if m:
            fields[m.group(1)] = bool(m.group(2))
    return fields


def resolve(expr: str, decls: dict[str, str]) -> dict[str, bool]:
    """Fields (name -> optional) of an interface/type expression with `&`, `Omit<>` and aliases."""
    expr = expr.strip()
    if expr.startswith("{"):
        return body_fields(expr)
    if len(_split_top(expr, "|")) > 1:
        raise ValueError(f"union types are not resolved: {expr[:40]}")
    result: dict[str, bool] = {}
    for part in _split_top(expr, "&"):
        omit = re.match(r"^Omit<\s*(\w+)\s*,\s*(.+)>$", part, re.S)
        if omit:
            dropped = set(re.findall(r'"(\w+)"', omit.group(2)))
            result.update({k: v for k, v in resolve(decls[omit.group(1)], decls).items() if k not in dropped})
        elif part.startswith("{"):
            result.update(body_fields(part))
        else:
            result.update(resolve(decls[part], decls))
    return result


@pytest.fixture(scope="module")
def decls() -> dict[str, str]:
    return parse_declarations(TYPES_TS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def schemas() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))["components"]["schemas"]


# --- the parser itself --------------------------------------------------------------------------


def test_parser_reads_intersections_and_omit(decls):
    stock = resolve(decls["StockItem"], decls)
    assert {"id", "name", "price", "invested", "paid_from"} <= set(stock)
    other = resolve(decls["OtherItem"], decls)
    assert "gain" in other and "maturity_date" in other
    pf = resolve(decls["PfItem"], decls)
    assert "extended_until" in pf and pf["maturity_date"] is False
    assert resolve(decls["ExitSummary"], decls)["left_in_account"] is False
    assert len(decls) > 100


# --- typed models vs OpenAPI --------------------------------------------------------------------


def test_every_mapped_name_exists(decls, schemas):
    assert not [n for n in TS_TO_SCHEMA if n not in decls], "TS names that no longer exist in types.ts"
    assert not [s for s in TS_TO_SCHEMA.values() if s not in schemas], "schema names missing from OpenAPI"


def test_ts_interfaces_only_name_fields_the_api_sends(decls, schemas):
    problems = []
    seen_drift = set()
    for ts_name, schema_name in sorted(TS_TO_SCHEMA.items()):
        ts_fields = resolve(decls[ts_name], decls)
        api_fields = set(schemas[schema_name].get("properties", {}))
        for field in sorted(ts_fields):
            if field in api_fields:
                continue
            if field in KNOWN_DRIFT.get(ts_name, {}):
                seen_drift.add((ts_name, field))
                continue
            problems.append(f"{ts_name}.{field} is not a property of OpenAPI {schema_name}")
    assert not problems, "TS fields the API does not send (fix types.ts or the API, or list in KNOWN_DRIFT):\n  " + "\n  ".join(problems)
    declared = {(t, f) for t, fields in KNOWN_DRIFT.items() for f in fields}
    assert declared == seen_drift, f"KNOWN_DRIFT entries that no longer drift: {sorted(declared - seen_drift)}"


# --- holding items vs real responses ------------------------------------------------------------

BODIES = {"fd": FD, "rd": RD, "stock": STOCK, "bond": BOND, "gold": GOLD, "cash": CASH, "other": OTHER}
PF = {
    "name": "Company EPF", "kind": "ppf", "balance": 100000, "balance_date": "2025-10-01",
    "interest_rate": 8.25, "opened_on": "2020-04-10",
}  # fmt: skip
NPS = {"scheme_id": "SM001003", "units": 1000.1234, "contributed": 40000, "start_date": "2025-10-01"}


class _InlinePool:
    """ThreadPoolExecutor stand-in that runs each submitted call immediately, on this thread."""

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001 - mirror the executor: the error shows on result()
            future.set_exception(exc)
        return future


@pytest.fixture
def seeded(sc, users, auth_engine, monkeypatch):  # noqa: F811
    """One holding of each type for user A; returns (client, headers, {slug: id})."""
    from app.routers import assets as assets_router
    from app.routers import portfolio as portfolio_router

    a = users[0]
    for table in (GoldRateHistory, StockPriceLatest):
        table.__table__.create(auth_engine, checkfirst=True)
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            NpsMaster(
                scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E",
            )
        )  # fmt: skip
        session.flush()
        session.add(NpsNavLatest(scheme_id="SM001003", nav=50, nav_date=date(2026, 2, 27)))
        session.commit()
    # Adding an NPS holding schedules a background NAV history sync (network): turn it off.
    monkeypatch.setattr(assets_router.nps, "sync_scheme_safely", lambda *args, **kwargs: None)
    # The portfolio queries run in threads; the test SQLite shares ONE connection, so run them inline.
    monkeypatch.setattr(portfolio_router, "ThreadPoolExecutor", _InlinePool)
    ids = {slug: add(sc, a, slug, body) for slug, body in {**BODIES, "mf": FUND, "pf": PF, "nps": NPS}.items()}
    return sc, a, ids


def _assert_keys(slug, keys, decls, where):
    ts_name = ITEM_TYPES[slug]
    missing = []
    for field, optional in sorted(resolve(decls[ts_name], decls).items()):
        if optional or field in keys or field in OPTIONAL.get(slug, set()):
            continue
        if field in KNOWN_DRIFT.get(ts_name, {}):
            continue
        missing.append(field)
    assert not missing, f"{ts_name} fields missing from {where} for {slug}: {missing}"


def test_holding_item_types_match_real_responses(seeded, decls):
    client, headers, ids = seeded
    assert set(ids) == set(ITEM_TYPES), "seed one holding per asset type"
    for slug, item_id in ids.items():
        grid = client.get(f"/api/holdings/{slug}", headers=headers)
        assert grid.status_code == 200, (slug, grid.json())
        rows = grid.json()["items"]
        assert len(rows) == 1, slug
        _assert_keys(slug, set(rows[0]), decls, f"GET /api/holdings/{slug}")

        detail = client.get(f"/api/holdings/{slug}/{item_id}", headers=headers)
        assert detail.status_code == 200, (slug, detail.json())
        _assert_keys(slug, set(detail.json()["item"]), decls, f"GET /api/holdings/{slug}/{item_id}")

    portfolio = client.get("/api/portfolio", headers=headers)
    assert portfolio.status_code == 200
    groups = {g["type"]: g for g in portfolio.json()["groups"]}
    for slug in ids:
        assert groups[slug]["items"], slug
        _assert_keys(slug, set(groups[slug]["items"][0]), decls, "GET /api/portfolio")


def test_dashboard_keys_match_the_ts_type(seeded, decls):
    client, headers, _ = seeded
    body = client.get("/api/dashboard", headers=headers).json()
    for field, optional in resolve(decls["DashboardResponse"], decls).items():
        assert optional or field in body, f"DashboardResponse.{field} missing from GET /api/dashboard"
    row_fields = resolve(decls["DashboardByType"], decls)
    assert body["by_type"], "dashboard has no rows for the seeded holdings"
    for field, optional in row_fields.items():
        assert optional or field in body["by_type"][0], f"DashboardByType.{field} missing"
