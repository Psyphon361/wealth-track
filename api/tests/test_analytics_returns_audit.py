"""Audit of the Returns maths: an independent XIRR reference, per-type flows built from the items
`build_groups` really produces (real ORM rows -> valuation -> read schema JSON), and invariants on
a mixed portfolio. No DB, no network. today = 2026-11-02."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from dateutil.relativedelta import relativedelta

from app.models import (
    Bond,
    Cash,
    FixedDeposit,
    Gold,
    MutualFund,
    Nps,
    NpsMaster,
    Other,
    Pf,
    RecurringDeposit,
    Stock,
)
from app.routers.portfolio import build_groups
from app.services import analytics_benchmark as ab
from app.services import analytics_returns as ar
from app.services import valuation
from app.services.valuation import mf_xirr, xirr

D = Decimal
TODAY = date(2026, 11, 2)
NOW = datetime(2026, 1, 1)
PP = 0.01  # tolerance in percentage points


# --- Independent XIRR reference (bisection on NPV, actual/365 from the earliest flow) ----------


def ref_xirr(flows):
    first = min(d for d, _ in flows)
    pts = [((d - first).days / 365, float(a)) for d, a in flows]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in pts)

    lo, hi = -0.9999, 100.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(400):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def pct(rate):
    return rate * 100


def _d(y, m, d):
    return date(y, m, d)


def _sip(start, months, amount):
    return [(start + relativedelta(months=k), D(-amount)) for k in range(months)]


XIRR_CASES = {
    "single_buy": [(_d(2024, 1, 15), D(-1000)), (TODAY, D(1500))],
    "sip_monthly": _sip(_d(2024, 11, 5), 24, 10000) + [(TODAY, D(280000))],
    "buys_and_redemptions": [
        (_d(2022, 3, 1), D(-50000)),
        (_d(2023, 6, 10), D(-20000)),
        (_d(2024, 2, 20), D(30000)),
        (_d(2025, 1, 5), D(-10000)),
        (_d(2025, 9, 9), D(15000)),
        (TODAY, D(60000)),
    ],
    "loss": [(_d(2025, 9, 28), D(-1000)), (TODAY, D(600))],
    "near_zero_up": [(_d(2025, 9, 28), D(-100000)), (TODAY, D(100050))],
    "near_zero_down": [(_d(2025, 9, 28), D(-100000)), (TODAY, D(99950))],
    "very_high": [(TODAY - timedelta(days=365), D(-100)), (TODAY, D(5000))],
    "same_day_flows": [
        (_d(2024, 5, 1), D(-500)),
        (_d(2024, 5, 1), D(-500)),
        (TODAY, D(1200)),
    ],
    "same_day_buy_sell_then_value": [
        (_d(2024, 5, 1), D(-1000)),
        (_d(2025, 5, 1), D(400)),
        (_d(2025, 5, 1), D(-100)),
        (TODAY, D(900)),
    ],
}


@pytest.mark.parametrize("name", list(XIRR_CASES))
def test_xirr_matches_independent_reference(name):
    flows = XIRR_CASES[name]
    got = xirr(flows)
    want = ref_xirr(flows)
    assert got is not None and want is not None
    assert abs(pct(float(got)) - pct(want)) < PP


def test_xirr_all_on_one_date_is_none():
    assert xirr([(TODAY, D(-100)), (TODAY, D(110))]) is None


def test_xirr_no_sign_change_is_none():
    assert xirr([(_d(2024, 1, 1), D(-100)), (TODAY, D(-5))]) is None


def test_xirr_is_order_independent():
    flows = XIRR_CASES["buys_and_redemptions"]
    assert abs(float(xirr(flows)) - float(xirr(list(reversed(flows))))) < 1e-9


def test_xirr_uses_actual_365_day_count():
    # Exactly 730 days at 10 % a year (actual/365): 1000 -> 1210.
    flows = [(TODAY - timedelta(days=730), D(-1000)), (TODAY, D(1210))]
    assert abs(float(xirr(flows)) - 0.10) < 1e-6


# --- Real item shapes through build_groups -----------------------------------------------------


def mk(cls, **kw):
    return cls(user_id=1, created_at=NOW, updated_at=NOW, deleted_at=None, **kw)


def fd_row(id_, principal=100000, start=_d(2024, 11, 2), years=3, payout="cumulative", rate=8):
    return mk(
        FixedDeposit, id=id_, bank=f"Bank {id_}", principal=principal, rate=rate,
        start_date=start, compounding="quarterly", payout_type=payout, tenure_years=years,
        tenure_months=0, tenure_days=0,
    )  # fmt: skip


def rd_row(id_, start, months, instalment=1000, rate=6):
    return mk(
        RecurringDeposit, id=id_, bank=f"RD {id_}", monthly_instalment=instalment, rate=rate,
        start_date=start, compounding="quarterly", tenure_years=0, tenure_months=months,
        tenure_days=0,
    )  # fmt: skip


def stock_row(id_, qty=10, price=100, buy=_d(2024, 1, 1), master=1):
    return mk(
        Stock, id=id_, name=f"Stock {id_}", exchange="NSE", master_id=master, quantity=qty,
        avg_buy_price=price, buy_date=buy,
    )  # fmt: skip


def bond_row(id_, invested=10000, buy=_d(2024, 1, 1), maturity=_d(2030, 1, 1), ytm=7):
    return mk(
        Bond, id=id_, name=f"Bond {id_}", issuer="X", bond_type="corporate", quantity=10,
        face_value=1000, purchase_price=1000, invested_amount=invested, purchase_date=buy,
        ytm=ytm, maturity_date=maturity,
    )  # fmt: skip


def gold_row(id_, invested=50000, buy=_d(2024, 1, 1), grams=10):
    return mk(
        Gold, id=id_, name=f"Gold {id_}", form="jewellery", metal="gold", purity="916",
        weight_grams=grams, purchase_date=buy, invested_amount=invested,
    )  # fmt: skip


def mf_row(id_, code=100, units=100, invested=4000, buy=_d(2024, 1, 1)):
    return mk(
        MutualFund, id=id_, scheme_name=f"Fund {id_}", scheme_code=code, category="equity",
        units=units, avg_nav=40, invested_amount=invested, purchase_date=buy,
    )  # fmt: skip


def other_row(id_, current=100000, invested=None, acquired=None):
    return mk(
        Other, id=id_, name=f"Other {id_}", category="Art", current_value=current,
        value_date=TODAY, invested_amount=invested, acquired_on=acquired,
    )  # fmt: skip


def groups_of(records, *, nav=None, price=None, rate=None):
    navs = {c: (D(nav), TODAY) for c in (100, 101, 102)} if nav is not None else {}
    prices = (
        {m: SimpleNamespace(price=D(price), prev_close=D(price), price_time=None, source="t")
         for m in (1, 2, 3)}
        if price is not None
        else {}
    )  # fmt: skip
    rates = {("gold", "916"): (D(rate), TODAY)} if rate is not None else {}
    return build_groups(records, TODAY, navs, prices, {}, rates, {}, {})


def only_item(records, slug, **kw):
    return groups_of(records, **kw)[[g["type"] for g in groups_of(records, **kw)].index(slug)][
        "items"
    ][0]


def txn(day, kind, units, amount):
    return SimpleNamespace(txn_date=day, kind=kind, units=D(units), amount=D(amount))


def flows_ref_pct(flows):
    return pct(ref_xirr(flows))


def test_fd_cumulative_flows_and_return():
    item = only_item({"fd": [fd_row(1)]}, "fd")
    built = ar.holding_flows("fd", item, TODAY)
    assert built.basis == "purchase_date"
    assert built.flows == [(_d(2024, 11, 2), D("-100000.0")), (TODAY, D(str(item["current_value"])))]
    out = ar.returns(groups_of({"fd": [fd_row(1)]}), TODAY)
    assert out["overall"]["annualised"] is True
    assert abs(float(out["overall"]["return_pct"]) - flows_ref_pct(built.flows)) < PP
    # An 8 % quarterly FD held ~2 years: effective annual rate is 8.24 %.
    assert abs(float(out["overall"]["return_pct"]) - 8.24) < 0.05


def test_fd_matured_is_not_a_return_holding():
    groups = groups_of({"fd": [fd_row(1, start=_d(2020, 1, 1), years=2)]})
    assert groups[0]["items"][0]["status"] == "matured"
    out = ar.returns(groups, TODAY)
    assert out["overall"] is None and out["by_type"] == []
    assert sum(out["excluded"].values()) == 0


def test_payout_fd_return_includes_interest_received():
    rows = {"fd": [fd_row(1, start=_d(2024, 11, 2), years=3, payout="payout")]}
    groups = groups_of(rows)
    item = groups[0]["items"][0]
    assert item["interest_received"] > 0
    out = ar.returns(groups, TODAY)
    assert abs(out["overall"]["gain"] - D(str(item["gain"]))) < D("0.01")
    assert 7 < float(out["overall"]["return_pct"]) < 9


@pytest.mark.parametrize(
    "start",
    [_d(2025, 1, 1), _d(2025, 1, 29), _d(2025, 1, 30), _d(2025, 1, 31), _d(2025, 8, 31),
     _d(2025, 3, 31), _d(2024, 2, 29), _d(2025, 5, 30), _d(2025, 2, 28)],
)  # fmt: skip
def test_rd_instalment_count_matches_valuation(start):
    # Starts on the 29th/30th/31st, which clamp in shorter months.
    rd = rd_row(1, start, months=18)
    groups = groups_of({"rd": [rd]})
    item = groups[1]["items"][0]
    built = ar.holding_flows("rd", item, TODAY)
    maturity = start + relativedelta(months=18)
    expected_dates = []
    k = 0
    while True:
        d = start + relativedelta(months=k)
        if d >= maturity or d > TODAY:
            break
        expected_dates.append(d)
        k += 1
    n = len(built.flows) - 1
    assert [d for d, _ in built.flows[:-1]] == expected_dates
    assert n * 1000 == pytest.approx(item["invested"])
    assert all(a == D(-1000) for _, a in built.flows[:-1])
    assert built.flows[-1] == (TODAY, D(str(item["current_value"])))
    # Clamped dates never repeat or go backwards.
    assert expected_dates == sorted(set(expected_dates))


def test_rd_flow_on_today_is_included_and_matches_valuation():
    start = TODAY - relativedelta(months=3)
    item = groups_of({"rd": [rd_row(1, start, 12)]})[1]["items"][0]
    built = ar.holding_flows("rd", item, TODAY)
    assert built.flows[-2] == (TODAY, D(-1000))
    assert len(built.flows) - 1 == 4 and item["invested"] == 4000


def test_rd_matured_before_today_is_not_active():
    start = _d(2024, 1, 31)
    groups = groups_of({"rd": [rd_row(1, start, 6)]})
    assert groups[1]["items"][0]["status"] == "matured"
    assert ar.returns(groups, TODAY)["overall"] is None


def test_rd_flow_sum_equals_invested_for_every_month_end_start():
    for m in range(1, 13):
        for d in (29, 30, 31):
            try:
                start = date(2025, m, d)
            except ValueError:
                continue
            item = groups_of({"rd": [rd_row(1, start, 24)]})[1]["items"][0]
            built = ar.holding_flows("rd", item, TODAY)
            assert -sum(a for _, a in built.flows[:-1]) == D(str(item["invested"])), start


def test_bond_stock_gold_flows_use_their_own_dates():
    groups = groups_of(
        {
            "bond": [bond_row(1, buy=_d(2024, 3, 3))],
            "stock": [stock_row(1, buy=_d(2023, 4, 4))],
            "gold": [gold_row(1, buy=_d(2022, 5, 5))],
        },
        price=150,
        rate=7000,
    )
    by = {g["type"]: g["items"][0] for g in groups if g["items"]}
    for slug, start in (("bond", _d(2024, 3, 3)), ("stock", _d(2023, 4, 4)), ("gold", _d(2022, 5, 5))):
        built = ar.holding_flows(slug, by[slug], TODAY)
        assert built.reason is None and built.basis == "purchase_date"
        assert built.flows == [
            (start, -D(str(by[slug]["invested"]))),
            (TODAY, D(str(by[slug]["current_value"]))),
        ]


def test_gold_return_matches_valuation_xirr_field():
    item = only_item({"gold": [gold_row(1, buy=_d(2023, 1, 1))]}, "gold", rate=7000)
    out = ar.returns(groups_of({"gold": [gold_row(1, buy=_d(2023, 1, 1))]}, rate=7000), TODAY)
    assert abs(float(out["overall"]["return_pct"]) - item["xirr"]) < PP


def test_unpriced_items_are_at_cost():
    groups = groups_of(
        {"stock": [stock_row(1)], "mf": [mf_row(1)], "gold": [gold_row(1)]}
    )  # no price, no nav, no rate
    out = ar.returns(groups, TODAY)
    assert out["overall"] is None
    assert out["excluded"] == {"at_cost": 3, "no_flows": 0, "other_without_invested": 0}


def test_stock_without_master_is_at_cost():
    out = ar.returns(groups_of({"stock": [stock_row(1, master=None)]}, price=150), TODAY)
    assert out["excluded"]["at_cost"] == 1


@pytest.mark.parametrize(
    "invested,acquired,reason",
    [
        (None, None, "other_without_invested"),
        (None, _d(2023, 1, 1), "other_without_invested"),
        (50000, None, "other_without_invested"),
        (50000, _d(2023, 1, 1), None),
    ],
)
def test_other_flows(invested, acquired, reason):
    item = only_item({"other": [other_row(1, 100000, invested, acquired)]}, "other")
    built = ar.holding_flows("other", item, TODAY)
    assert built.reason == reason
    if reason is None:
        assert built.flows == [(_d(2023, 1, 1), D(-50000)), (TODAY, D(100000))]
        out = ar.returns(groups_of({"other": [other_row(1, 100000, invested, acquired)]}), TODAY)
        row = out["overall"]
        assert row["invested"] == 50000 and row["current"] == 100000 and row["gain"] == 50000
        assert abs(float(row["return_pct"]) - flows_ref_pct(built.flows)) < PP


def test_other_with_zero_invested_amount_is_excluded_not_crashing():
    out = ar.returns(groups_of({"other": [other_row(1, 100, 0, _d(2023, 1, 1))]}), TODAY)
    assert out["overall"] is None
    assert out["excluded"]["no_flows"] == 1


def test_mf_with_transactions_including_redemption_matches_mf_xirr():
    mf = mf_row(1, units=60, invested=3000, buy=_d(2023, 1, 1))
    txns = [
        txn(_d(2023, 1, 1), "purchase", 100, 4000),
        txn(_d(2024, 1, 1), "purchase", 50, 2500),
        txn(_d(2025, 1, 1), "redemption", 90, 5400),
    ]
    groups = groups_of({"mf": [mf]}, nav=70)
    item = [g for g in groups if g["type"] == "mf"][0]["items"][0]
    built = ar.holding_flows("mf", item, TODAY, txns)
    assert built.basis == "transactions"
    assert built.flows == [
        (_d(2023, 1, 1), D(-4000)),
        (_d(2024, 1, 1), D(-2500)),
        (_d(2025, 1, 1), D(5400)),
        (TODAY, D(str(item["current_value"]))),
    ]
    out = ar.returns(groups, TODAY, mf_transactions={1: txns})
    want, basis, used = mf_xirr(
        D(str(item["units"])), D(str(item["invested"])), item["purchase_date"],
        D(str(item["current_value"])), txns, TODAY,
    )  # fmt: skip
    assert basis == "transactions" and used == 3
    assert out["overall"]["return_pct"] == want
    assert abs(float(want) - flows_ref_pct(built.flows)) < PP


def test_mf_via_purchase_date_when_units_do_not_match_equals_mf_xirr():
    mf = mf_row(1, units=100, invested=4000, buy=_d(2023, 1, 1))
    txns = [txn(_d(2023, 1, 1), "purchase", 40, 1600)]  # net 40 != 100 units
    groups = groups_of({"mf": [mf]}, nav=70)
    item = [g for g in groups if g["type"] == "mf"][0]["items"][0]
    assert ar.holding_flows("mf", item, TODAY, txns).basis == "purchase_date"
    out = ar.returns(groups, TODAY, mf_transactions={1: txns})
    want, basis, _ = mf_xirr(
        D(str(item["units"])), D(str(item["invested"])), item["purchase_date"],
        D(str(item["current_value"])), txns, TODAY,
    )  # fmt: skip
    assert basis == "purchase_date"
    assert out["overall"]["return_pct"] == want
    # Without any transactions at all.
    out2 = ar.returns(groups, TODAY)
    assert out2["overall"]["return_pct"] == want and out2["overall"]["basis"] == "purchase_date"


def test_mf_net_units_tolerance_boundary():
    mf = mf_row(1, units=100, invested=4000, buy=_d(2023, 1, 1))
    groups = groups_of({"mf": [mf]}, nav=70)
    item = [g for g in groups if g["type"] == "mf"][0]["items"][0]
    ok = [txn(_d(2023, 1, 1), "purchase", "100.01", 4000)]
    bad = [txn(_d(2023, 1, 1), "purchase", "100.02", 4000)]
    assert ar.holding_flows("mf", item, TODAY, ok).basis == "transactions"
    assert ar.holding_flows("mf", item, TODAY, bad).basis == "purchase_date"


def test_mf_full_redemption_history_keeps_cash_back_in_flows():
    # Units held 0 after a redemption would not be an active holding with a NAV, but a partial
    # redemption leaves proceeds in the XIRR flows while `invested` stays the holding's own.
    mf = mf_row(1, units=50, invested=2000, buy=_d(2023, 1, 1))
    txns = [txn(_d(2023, 1, 1), "purchase", 100, 4000), txn(_d(2024, 1, 1), "redemption", 50, 3000)]
    groups = groups_of({"mf": [mf]}, nav=60)
    out = ar.returns(groups, TODAY, mf_transactions={1: txns})
    assert out["overall"]["invested"] == 2000


# --- Invariants on a mixed portfolio -----------------------------------------------------------


def mixed():
    records = {
        "fd": [fd_row(1), fd_row(2, start=_d(2025, 12, 1)), fd_row(3, start=_d(2019, 1, 1), years=2)],
        "rd": [rd_row(1, _d(2025, 2, 10), 24), rd_row(2, _d(2026, 9, 1), 12)],
        "stock": [stock_row(1), stock_row(2, buy=_d(2026, 6, 1)), stock_row(3, master=9)],
        "bond": [bond_row(1), bond_row(2, buy=_d(2026, 10, 1))],
        "mf": [mf_row(1, code=100), mf_row(2, code=101, buy=_d(2026, 8, 1)), mf_row(3, code=999)],
        "nps": [nps_row(1)],
        "gold": [gold_row(1), gold_row(2, buy=_d(2026, 1, 1))],
        "cash": [mk(Cash, id=1, name="c", kind="savings", balance=5000, balance_date=TODAY)],
        "pf": [
            mk(Pf, id=1, name="p", kind="epf", balance=100000, balance_date=TODAY,
               interest_rate=D("8.25")),
        ],
        "other": [
            other_row(1, 100000, 50000, _d(2022, 1, 1)),
            other_row(2, 3000),
            other_row(3, 9000, 8000, None),
        ],
    }  # fmt: skip
    return records


def nps_row(id_):
    row = mk(Nps, id=id_, scheme_id="SM1", units=10, contributed=1000, start_date=_d(2023, 1, 1))
    row.master = NpsMaster(
        scheme_id="SM1", pfm_code="P1", pfm_name="PFM", scheme_name="Scheme E", tier="I",
        asset_class="E",
    )
    return row


def active_count(groups):
    return sum(1 for g in groups for i in g["items"] if i["status"] == "active")


def test_group_sums_agree_and_counts_add_up():
    groups = groups_of(mixed(), nav=70, price=150, rate=7000)
    out = ar.returns(groups, TODAY)
    ov = out["overall"]
    for rows in (out["by_type"], out["by_class"]):
        assert sum(r["holdings"] for r in rows) == ov["holdings"]
        for key in ("invested", "current", "gain"):
            assert abs(sum(r[key] for r in rows) - ov[key]) <= D("0.02")
    assert ov["gain"] == ov["current"] - ov["invested"]
    for r in out["by_type"] + out["by_class"] + [ov]:
        assert abs(r["gain"] - (r["current"] - r["invested"])) <= D("0.01")
    assert ov["holdings"] + sum(out["excluded"].values()) == active_count(groups)
    # Excluded breakdown for this fixture: unpriced stock+MF = 2, cash/pf/nps = 3, other = 2.
    assert out["excluded"] == {"at_cost": 2, "no_flows": 3, "other_without_invested": 2}


def test_overall_since_is_earliest_flow():
    groups = groups_of(mixed(), nav=70, price=150, rate=7000)
    out = ar.returns(groups, TODAY)
    assert out["overall"]["since"] == min(r["since"] for r in out["by_type"])
    assert out["overall"]["since"] == _d(2022, 1, 1)


def _fd_group_days(days, current_rate=8):
    start = TODAY - timedelta(days=days)
    return groups_of({"fd": [fd_row(1, start=start, years=5)]})


@pytest.mark.parametrize("days,annualised", [(364, False), (365, True), (366, True)])
def test_365_day_boundary(days, annualised):
    groups = _fd_group_days(days)
    item = groups[0]["items"][0]
    out = ar.returns(groups, TODAY)
    row = out["overall"]
    assert row["annualised"] is annualised
    gain_pct = round(item["gain"] / item["invested"] * 100, 2)
    if annualised:
        flows = [(TODAY - timedelta(days=days), -D(str(item["invested"]))),
                 (TODAY, D(str(item["current_value"])))]  # fmt: skip
        assert abs(float(row["return_pct"]) - flows_ref_pct(flows)) < PP
    else:
        assert float(row["return_pct"]) == pytest.approx(gain_pct, abs=0.011)


def test_best_worst_holdings_under_six_months_never_listed():
    groups = groups_of({"fd": [fd_row(1, start=TODAY - timedelta(days=150), years=5)]})
    out = ar.returns(groups, TODAY)
    assert out["best"] == [] and out["worst"] == []


def test_best_worst_lists_holdings_between_six_and_twelve_months():
    groups = groups_of({"fd": [fd_row(1, start=TODAY - timedelta(days=364), years=5)]})
    out = ar.returns(groups, TODAY)
    assert [r["id"] for r in out["best"]] == [1] and out["worst"] == []
    assert out["overall"]["annualised"] is False


def _stocks_with_prices(prices):
    recs = [stock_row(i + 1, master=i + 1, price=100) for i in range(len(prices))]
    book = {
        i + 1: SimpleNamespace(price=D(p), prev_close=D(p), price_time=None, source="t")
        for i, p in enumerate(prices)
    }
    return build_groups({"stock": recs}, TODAY, {}, book, {}, {}, {}, {})


@pytest.mark.parametrize("n", [1, 3, 5, 6, 7, 10, 12])
def test_best_worst_ordering_and_no_overlap(n):
    prices = [60 + 17 * i for i in range(n)]  # distinct returns
    groups = _stocks_with_prices(prices)
    out = ar.returns(groups, TODAY)
    best, worst = out["best"], out["worst"]
    assert len(best) == min(5, n) and len(worst) == min(5, max(0, n - 5))
    assert [b["return_pct"] for b in best] == sorted((b["return_pct"] for b in best), reverse=True)
    assert [w["return_pct"] for w in worst] == sorted(w["return_pct"] for w in worst)
    assert not {b["id"] for b in best} & {w["id"] for w in worst}
    all_rets = sorted(
        (float(h) for h in (b["return_pct"] for b in best + worst)), reverse=True
    )
    assert all_rets[0] == max(float(b["return_pct"]) for b in best)
    if worst:
        assert float(worst[0]["return_pct"]) == min(float(w["return_pct"]) for w in worst)
        assert min(float(w["return_pct"]) for w in worst) <= min(float(b["return_pct"]) for b in best)


def test_best_worst_ties_are_deterministic_whatever_the_input_order():
    prices = [150] * 8  # eight holdings with identical returns
    groups = _stocks_with_prices(prices)
    a = ar.returns(groups, TODAY)
    reversed_groups = [{**g, "items": list(reversed(g["items"]))} for g in groups]
    b = ar.returns(reversed_groups, TODAY)
    assert [r["id"] for r in a["best"]] == [r["id"] for r in b["best"]]
    assert [r["id"] for r in a["worst"]] == [r["id"] for r in b["worst"]]
    assert not {r["id"] for r in a["best"]} & {r["id"] for r in a["worst"]}
    assert len(a["best"]) == 5 and len(a["worst"]) == 3


def test_best_worst_exclude_at_cost_holdings():
    recs = [stock_row(1, master=1), stock_row(2, master=2), stock_row(3, master=77)]
    prices = {
        1: SimpleNamespace(price=D(200), prev_close=D(200), price_time=None, source="t"),
        2: SimpleNamespace(price=D(50), prev_close=D(50), price_time=None, source="t"),
    }
    groups = build_groups({"stock": recs}, TODAY, {}, prices, {}, {}, {}, {})
    out = ar.returns(groups, TODAY)
    ids = {r["id"] for r in out["best"] + out["worst"]}
    assert ids == {1, 2} and out["excluded"]["at_cost"] == 1
    assert out["overall"]["holdings"] == 2


def test_best_worst_gain_is_current_minus_invested():
    out = ar.returns(_stocks_with_prices([150, 50]), TODAY)
    gains = {r["id"]: r["gain"] for r in out["best"] + out["worst"]}
    assert gains == {1: D("500.00"), 2: D("-500.00")}


def test_group_return_is_xirr_over_concatenated_flows():
    groups = groups_of(
        {"stock": [stock_row(1, buy=_d(2023, 1, 1)), stock_row(2, buy=_d(2024, 6, 1))]}, price=150
    )
    out = ar.returns(groups, TODAY)
    flows = [(_d(2023, 1, 1), D(-1000)), (TODAY, D(1500)), (_d(2024, 6, 1), D(-1000)), (TODAY, D(1500))]
    assert abs(float(out["overall"]["return_pct"]) - flows_ref_pct(flows)) < PP
    assert out["overall"]["basis"] == "purchase_date"


def test_mixed_basis_label():
    groups = groups_of(
        {"stock": [stock_row(1, buy=_d(2023, 1, 1))], "rd": [rd_row(1, _d(2025, 2, 10), 24)]},
        price=150,
    )
    out = ar.returns(groups, TODAY)
    assert out["overall"]["basis"] == "mixed"


def test_holding_less_than_year_inside_older_group_still_annualises_group():
    groups = groups_of(
        {"stock": [stock_row(1, buy=_d(2023, 1, 1)), stock_row(2, buy=_d(2026, 10, 1))]}, price=150
    )
    out = ar.returns(groups, TODAY)
    assert out["overall"]["annualised"] is True
    by_id = {r["id"]: r for r in out["best"] + out["worst"]}
    assert set(by_id) == {1}  # the 1-month-old holding is not ranked


def test_future_dated_purchase_has_no_flows():
    groups = groups_of({"stock": [stock_row(1, buy=TODAY + timedelta(days=1))]}, price=150)
    out = ar.returns(groups, TODAY)
    assert out["overall"] is None and out["excluded"]["no_flows"] == 1


def test_purchase_today_is_under_a_year_and_absolute():
    groups = groups_of({"stock": [stock_row(1, buy=TODAY)]}, price=150)
    out = ar.returns(groups, TODAY)
    assert out["overall"]["annualised"] is False
    assert out["overall"]["return_pct"] == D("50.00")


def test_valuation_xirr_field_on_items_agrees_with_reference():
    # value_gold's own xirr and the returns module use the same solver.
    rec = gold_row(1, buy=_d(2023, 1, 1))
    v = valuation.value_gold(rec, TODAY, rate=D(7000), rate_date=TODAY)
    flows = [(_d(2023, 1, 1), -D(50000)), (TODAY, D(70000))]
    assert abs(float(v["xirr"]) - flows_ref_pct(flows)) < PP


# --- Sales: proceeds are flows, fully sold holdings are realised results (#14) -----------------


def ex(day, amount, cost, quantity=None, full=False):
    """A SALE exit as the router loads it (amount is already net of charges)."""
    return SimpleNamespace(
        exit_date=day, amount=D(amount), cost=D(cost),
        quantity=D(quantity) if quantity is not None else None,
        prev_state={"full": True} if full else {},
    )  # fmt: skip


def sale_returns(slug, records, exits, *, txns=None, **kw):
    """returns() over real items, with the sale exits keyed by (slug, holding id)."""
    return ar.returns(
        groups_of({slug: records}, **kw), TODAY,
        mf_transactions=txns or {}, sale_exits={(slug, r.id): exits for r in records},
    )  # fmt: skip


def item_of(slug, record, **kw):
    for g in groups_of({slug: [record]}, **kw):
        if g["type"] == slug:
            return g["items"][0]


def test_partly_sold_stock_adds_the_sale_and_the_original_cost():
    # Bought 10 at 100 on 2024-01-01; sold 4 on 2025-06-01 for 520 (cost 400); 6 left at 150.
    sale = ex(_d(2025, 6, 1), 520, 400, 4)
    item = item_of("stock", stock_row(1, qty=6), price=150)
    built = ar.holding_flows("stock", item, TODAY, exits=[sale])
    flows = [(_d(2024, 1, 1), D(-1000)), (_d(2025, 6, 1), D(520)), (TODAY, D(900))]
    assert built.flows == flows
    out = sale_returns("stock", [stock_row(1, qty=6)], [sale], price=150)
    overall = out["overall"]
    # invested = original cost, current = what is left, gain = unrealised (300) + realised (120).
    assert (overall["invested"], overall["current"], overall["gain"]) == (1000, 900, 420)
    assert abs(float(overall["return_pct"]) - flows_ref_pct(flows)) < PP
    assert out["excluded"]["at_cost"] == 0


def test_stock_sold_in_two_steps():
    sales = [ex(_d(2024, 9, 1), 300, 200, 2), ex(_d(2025, 6, 1), 330, 200, 2)]
    out = sale_returns("stock", [stock_row(1, qty=6)], sales, price=150)
    flows = [
        (_d(2024, 1, 1), D(-1000)), (_d(2024, 9, 1), D(300)), (_d(2025, 6, 1), D(330)),
        (TODAY, D(900)),
    ]  # fmt: skip
    overall = out["overall"]
    assert (overall["invested"], overall["gain"]) == (1000, 300 + 100 + 130)
    assert abs(float(overall["return_pct"]) - flows_ref_pct(flows)) < PP


def test_partly_sold_bond_and_gold_use_original_cost():
    bond = bond_row(1, invested=6000)
    bond_sale = ex(_d(2025, 3, 1), 4100, 4000, 4)
    built = ar.holding_flows("bond", item_of("bond", bond), TODAY, exits=[bond_sale])
    assert built.flows[0] == (_d(2024, 1, 1), D(-10000))
    assert built.flows[1] == (_d(2025, 3, 1), D(4100))
    assert len(built.flows) == 3 and built.basis == "purchase_date"
    gold = gold_row(1, invested=30000, grams=6)
    gold_sale = ex(_d(2025, 3, 1), 24000, 20000, 4)
    built = ar.holding_flows("gold", item_of("gold", gold, rate=7000), TODAY, exits=[gold_sale])
    assert built.flows == [
        (_d(2024, 1, 1), D(-50000)), (_d(2025, 3, 1), D(24000)), (TODAY, D(42000)),
    ]  # fmt: skip


def test_partly_sold_other_uses_original_cost():
    other = other_row(1, current=30000, invested=60000, acquired=_d(2024, 1, 1))
    sale = ex(_d(2025, 3, 1), 25000, 30000)
    built = ar.holding_flows("other", item_of("other", other), TODAY, exits=[sale])
    assert built.flows == [
        (_d(2024, 1, 1), D(-90000)), (_d(2025, 3, 1), D(25000)), (TODAY, D(30000)),
    ]  # fmt: skip


def test_fully_sold_stock_is_a_realised_result():
    sale = ex(_d(2025, 6, 1), 1500, 1000, 10, full=True)
    rec = stock_row(1, qty=10, price=100)
    rec.closed_on = _d(2025, 6, 1)
    # No price is given, yet a sold stock still counts (no at-cost exclusion).
    out = ar.returns(groups_of({"stock": [rec]}), TODAY, sale_exits={("stock", 1): [sale]})
    flows = [(_d(2024, 1, 1), D(-1000)), (_d(2025, 6, 1), D(1500))]
    overall = out["overall"]
    assert (overall["holdings"], overall["invested"], overall["current"]) == (1, 1000, 0)
    assert overall["gain"] == 500 and overall["annualised"] is True
    assert abs(float(overall["return_pct"]) - flows_ref_pct(flows)) < PP
    assert [h["id"] for h in out["best"]] == [1] and out["best"][0]["gain"] == 500
    assert out["by_type"][0]["key"] == "stock" and out["by_class"][0]["key"] == "equity"
    assert out["excluded"] == {"at_cost": 0, "no_flows": 0, "other_without_invested": 0}


def test_fully_sold_after_a_partial_sale_counts_the_cost_once():
    rec = stock_row(1, qty=6)  # 600 left when the rest was sold
    rec.closed_on = _d(2025, 9, 1)
    sales = [ex(_d(2025, 6, 1), 520, 400, 4), ex(_d(2025, 9, 1), 900, 600, 6, full=True)]
    out = ar.returns(groups_of({"stock": [rec]}), TODAY, sale_exits={("stock", 1): sales})
    assert out["overall"]["invested"] == 1000
    assert out["overall"]["gain"] == 120 + 300


def test_sold_holding_without_a_sale_row_is_skipped():
    rec = stock_row(1)
    rec.closed_on = _d(2025, 6, 1)
    assert ar.returns(groups_of({"stock": [rec]}), TODAY)["overall"] is None


def test_sold_other_without_invested_stays_excluded_and_with_invested_counts():
    sale = ex(_d(2025, 6, 1), 120000, 100000, full=True)
    no_cost = other_row(1)
    no_cost.closed_on = _d(2025, 6, 1)
    out = sale_returns("other", [no_cost], [sale])
    assert out["overall"] is None
    costed = other_row(2, invested=100000, acquired=_d(2024, 1, 1))
    costed.closed_on = _d(2025, 6, 1)
    out = sale_returns("other", [costed], [sale])
    assert (out["overall"]["invested"], out["overall"]["gain"]) == (100000, 20000)
    assert out["overall"]["current"] == 0


def test_undoing_a_sale_puts_the_old_numbers_back():
    full_groups = groups_of({"stock": [stock_row(1, qty=10)]}, price=150)
    before = ar.returns(full_groups, TODAY)
    sold = ar.returns(
        groups_of({"stock": [stock_row(1, qty=6)]}, price=150), TODAY,
        sale_exits={("stock", 1): [ex(_d(2025, 6, 1), 520, 400, 4)]},
    )  # fmt: skip
    assert sold["overall"]["current"] == 900 != before["overall"]["current"]
    assert ar.returns(full_groups, TODAY, sale_exits={}) == before


def test_matured_holdings_never_reach_the_sold_path():
    groups = groups_of({"fd": [fd_row(1)]})
    groups[0]["items"][0]["status"] = "matured"
    assert ar.returns(groups, TODAY)["overall"] is None


def test_mf_transactions_basis_already_holds_a_manual_sale():
    txns = [txn(_d(2023, 1, 1), "purchase", 100, 4000), txn(_d(2025, 1, 1), "redemption", 40, 2400)]
    mf = mf_row(1, units=60, invested=2400, buy=_d(2023, 1, 1))
    sale = ex(_d(2025, 1, 1), 2400, 1600, 40)
    out = sale_returns("mf", [mf], [sale], txns={1: txns}, nav=70)
    built = ar.holding_flows("mf", item_of("mf", mf, nav=70), TODAY, txns, [sale])
    flows = [(_d(2023, 1, 1), D(-4000)), (_d(2025, 1, 1), D(2400)), (TODAY, D(4200))]
    assert built.basis == "transactions" and built.flows == flows  # sale not added twice
    overall = out["overall"]
    assert (overall["invested"], overall["current"], overall["gain"]) == (4000, 4200, 2600)
    assert abs(float(overall["return_pct"]) - flows_ref_pct(flows)) < PP


def test_mf_single_purchase_basis_adds_the_sale():
    mf = mf_row(1, units=60, invested=2400, buy=_d(2023, 1, 1))  # no transactions stored
    sale = ex(_d(2025, 1, 1), 2400, 1600, 40)
    built = ar.holding_flows("mf", item_of("mf", mf, nav=70), TODAY, (), [sale])
    assert built.basis == "purchase_date"
    assert built.flows == [(_d(2023, 1, 1), D(-4000)), (_d(2025, 1, 1), D(2400)), (TODAY, D(4200))]


def test_fully_sold_mf_on_both_bases():
    sale = ex(_d(2025, 1, 1), 5000, 4000, 100, full=True)
    mf = mf_row(1, units=100, invested=4000, buy=_d(2023, 1, 1))
    mf.closed_on = _d(2025, 1, 1)
    txns = [txn(_d(2023, 1, 1), "purchase", 100, 4000), txn(_d(2025, 1, 1), "redemption", 100, 5000)]
    on_txns = sale_returns("mf", [mf], [sale], txns={1: txns}, nav=70)
    flows = [(_d(2023, 1, 1), D(-4000)), (_d(2025, 1, 1), D(5000))]
    assert on_txns["overall"]["basis"] == "transactions"
    assert (on_txns["overall"]["invested"], on_txns["overall"]["gain"]) == (4000, 1000)
    assert abs(float(on_txns["overall"]["return_pct"]) - flows_ref_pct(flows)) < PP
    on_purchase = sale_returns("mf", [mf], [sale], nav=70)
    assert on_purchase["overall"]["basis"] == "purchase_date"
    assert on_purchase["overall"]["return_pct"] == on_txns["overall"]["return_pct"]


def test_benchmark_replay_handles_a_sale_dated_today():
    navs = ab.BenchmarkNavs("Index", [(_d(2024, 1, 1), D(100)), (TODAY, D(150))])
    sale = ex(TODAY, 1800, 1000, 10, full=True)
    rec = stock_row(1, qty=10, price=100)
    rec.closed_on = TODAY
    out = ar.returns(
        groups_of({"stock": [rec]}), TODAY, sale_exits={("stock", 1): [sale]},
        benchmark_loader=lambda since: navs, cpi={},
    )  # fmt: skip
    assert out["overall"]["gain"] == 800
    # The sale is skipped like a terminal value: the index units are valued at the latest NAV.
    days = (TODAY - _d(2024, 1, 1)).days
    assert float(out["benchmark"]["overall"]["benchmark_pct"]) == pytest.approx(
        (1.5 ** (365 / days) - 1) * 100, abs=0.01
    )
