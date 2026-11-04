"""Tax tab maths (services/analytics_tax.py) and GET /api/analytics/tax. Expected figures are
hand-worked from the rules in the module docstring; `today` is 2026-11-04 unless stated.

A financial year window is (31 Mar before, 31 Mar end]: 365 days, e.g. FY 2026-27 is
(2026-03-31, 2027-03-31].
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Cash
from app.routers import analytics_tax as tax_router
from app.routers import portfolio
from app.services import analytics_tax as tax
from app.services import valuation
from tests.test_analytics_api import TODAY as API_TODAY
from tests.test_analytics_api import fixed_today, seeded, tables  # noqa: F401  (fixtures)
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

TODAY = date(2026, 11, 4)
FY26 = (date(2026, 3, 31), date(2027, 3, 31))
FY25 = (date(2025, 3, 31), date(2026, 3, 31))


def fd(principal=100000, rate=8, start=date(2026, 4, 1), compounding="quarterly",
       payout="cumulative", years=1, months=0):  # fmt: skip
    return SimpleNamespace(
        principal=Decimal(principal), rate=Decimal(rate), start_date=start,
        compounding=compounding, payout_type=payout, tenure_years=years,
        tenure_months=months, tenure_days=0,
    )


def rd(instalment=1000, rate=6, start=date(2026, 1, 1), months=12):
    return SimpleNamespace(
        monthly_instalment=Decimal(instalment), rate=Decimal(rate), start_date=start,
        compounding="quarterly", tenure_years=0, tenure_months=months, tenure_days=0,
    )


# --- Financial years ---------------------------------------------------------------------------


def test_fy_helpers():
    assert tax.fy_label(2026) == "2026-27"
    assert tax.fy_label(2099) == "2099-00"
    assert tax.fy_bounds(2026) == (date(2026, 4, 1), date(2027, 3, 31))
    assert tax.current_fy_start_year(date(2027, 3, 31)) == 2026
    assert tax.current_fy_start_year(date(2027, 4, 1)) == 2027
    assert tax.available_fys(TODAY) == [
        {"start_year": 2026, "label": "2026-27", "is_current": True},
        {"start_year": 2025, "label": "2025-26", "is_current": False},
    ]


# --- Window interest per type ------------------------------------------------------------------


def test_cumulative_fd_inside_the_year_simple_interest():
    # 8% simple on 100,000 from 1 Apr 2026 for a year; to 31 Mar 2027 is 364 of 365 days.
    assert tax.fd_interest(fd(compounding="simple"), *FY26) == pytest.approx(
        100000 * 0.08 * 364 / 365
    )
    assert tax.fd_interest(fd(compounding="simple"), FY26[0], TODAY) == pytest.approx(
        100000 * 0.08 * 217 / 365  # 1 Apr to 4 Nov 2026 = 217 days
    )


def test_cumulative_quarterly_fd_across_the_fy_boundary_splits_the_total():
    deposit = fd(start=date(2026, 1, 1))  # matures 2027-01-01
    first = tax.fd_interest(deposit, *FY25)
    second = tax.fd_interest(deposit, *FY26)
    # 89 days in FY 2025-26 (1 Jan to 31 Mar), then the rest up to maturity.
    assert first == pytest.approx(100000 * (1.02 ** (4 * 89 / 365) - 1))
    assert first + second == pytest.approx(100000 * (1.02**4 - 1))  # 8,243.22 in total
    assert first + second == pytest.approx(8243.216)


def test_fd_maturing_mid_year_stops_accruing():
    deposit = fd(rate=10, start=date(2025, 4, 1), compounding="simple", years=0, months=6)
    assert tax.fd_interest(deposit, *FY25) == pytest.approx(100000 * 0.10 * 183 / 365)
    assert tax.fd_interest(deposit, *FY26) == 0


def test_fd_starting_mid_year_accrues_from_its_start():
    deposit = fd(rate=12, start=date(2026, 10, 1), compounding="simple")
    assert tax.fd_interest(deposit, FY26[0], TODAY) == pytest.approx(12000 * 34 / 365)
    assert tax.fd_interest(deposit, *FY26) == pytest.approx(12000 * 181 / 365)
    assert tax.fd_interest(deposit, *FY25) == 0


def test_monthly_payout_fd_counts_payouts_dated_in_the_window():
    deposit = fd(principal=120000, rate=12, start=date(2026, 1, 15), compounding="monthly",
                 payout="payout")  # fmt: skip
    assert tax.fd_interest(deposit, *FY25) == pytest.approx(2400)  # 15 Feb and 15 Mar
    assert tax.fd_interest(deposit, *FY26) == pytest.approx(12000)  # 15 Apr 2026 to 15 Jan 2027
    assert tax.fd_interest(deposit, FY26[0], TODAY) == pytest.approx(7 * 1200)  # Apr to Oct


def test_quarterly_payout_fd_to_date_and_projected():
    deposit = fd(start=date(2026, 2, 1), compounding="quarterly", payout="payout")
    # 2,000 on 1 May, 1 Aug, 1 Nov 2026 and 1 Feb 2027.
    assert tax.fd_interest(deposit, FY26[0], TODAY) == pytest.approx(6000)
    assert tax.fd_interest(deposit, *FY26) == pytest.approx(8000)
    assert tax.fd_interest(deposit, *FY25) == 0


def test_rd_interest_is_growth_net_of_instalments():
    deposit = rd()  # 1,000 a month from 1 Jan 2026 for 12 months at 6% quarterly
    expected_fy25 = sum(
        1000 * (1.015 ** (4 * days / 365) - 1) for days in (89, 58, 30)  # 1 Jan, 1 Feb, 1 Mar
    )
    assert tax.rd_interest(deposit, *FY25) == pytest.approx(expected_fy25)
    total = tax.rd_interest(deposit, *FY25) + tax.rd_interest(deposit, *FY26)
    matured = valuation.value_rd(deposit, date(2027, 1, 1))
    assert total == pytest.approx(float(matured["current_value"] - matured["invested"]), abs=0.02)


def test_rd_instalment_on_the_first_day_of_the_year_belongs_to_that_year():
    deposit = rd(start=date(2026, 4, 1), months=3)
    # Instalments on 1 Apr, 1 May, 1 Jun; interest to 31 Mar 2027 stops at maturity 1 Jul.
    assert tax.rd_interest(deposit, *FY26) == pytest.approx(
        sum(1000 * (1.015 ** (4 * days / 365) - 1) for days in (91, 61, 30))
    )
    assert tax.rd_interest(deposit, *FY25) == 0


def test_value_rd_is_unchanged_by_the_dated_helper():
    deposit = rd(months=6)
    count, current = valuation.rd_position(deposit, TODAY)
    out = valuation.value_rd(deposit, TODAY)
    assert count == 6  # 1 Jan to 1 Jun, none at maturity (1 Jul)
    assert out["invested"] == Decimal("6000.00")
    assert out["current_value"] == Decimal(str(current)).quantize(Decimal("0.01"))


def test_savings_interest_is_balance_times_rate_times_days():
    assert tax.savings_interest(Decimal(100000), Decimal(3), *FY26) == Decimal(3000)
    assert tax.savings_interest(Decimal(73000), Decimal(4), FY26[0], date(2026, 6, 30)) == (
        Decimal(73000) * 4 / 100 * 91 / 365
    )
    assert tax.savings_interest(Decimal(1000), Decimal(3), date(2026, 5, 1), date(2026, 4, 1)) == 0


# --- Payers, thresholds, TDS -------------------------------------------------------------------


def item(id_, bank, principal, *, rate=10, start="2025-09-01", years=2, issuer_id=None,
         label=None, kind="fd", compounding="yearly", payout="payout", **extra):  # fmt: skip
    return {
        "id": id_, "bank": bank, "label": label, "issuer_id": issuer_id, "principal": principal,
        "rate": rate, "start_date": start, "tenure_years": years, "tenure_months": 0,
        "tenure_days": 0, "compounding": compounding, "payout_type": payout,
        "status": "active", **extra,
    }  # fmt: skip


def groups_of(*items, cash=(), bonds=0):
    return [
        {"type": "fd", "items": list(items)},
        {"type": "cash", "items": list(cash)},
        {"type": "bond", "items": [{"id": n} for n in range(bonds)]},
    ]


MASTERS = {
    1: SimpleNamespace(name="HDFC Bank Limited", short_name="HDFC Bank", category="private_sector",
                       merged_into_id=None),
    2: SimpleNamespace(name="HDFC Ltd", short_name="HDFC Ltd", category="hfc", merged_into_id=1),
    3: SimpleNamespace(name="Bajaj Finance Limited", short_name="Bajaj Finance",
                       category="nbfc", merged_into_id=None),
}  # fmt: skip


def overview(groups, masters=None, fy=None):
    return tax.tax_overview(groups, masters or {}, TODAY, fy)


def test_bank_threshold_exactly_50000_does_not_cross():
    # A yearly payout of 10% on 500,000 falls on 1 Sep 2026: exactly 50,000.00.
    body = overview(groups_of(item(1, "Some Bank", 500000), item(2, "Other", 1000, rate=1)))
    payer = next(p for p in body["payers"] if p["name"] == "Some Bank")
    assert payer["interest_projected"] == Decimal("50000.00")
    assert payer["threshold"] == 50000 and payer["kind"] == "bank"
    assert payer["crosses"] is False and payer["tds_estimate"] == 0


def test_bank_just_over_threshold_crosses_and_tds_is_ten_percent_of_all_of_it():
    body = overview(groups_of(item(1, "Some Bank", 500001)))
    payer = body["payers"][0]
    assert payer["interest_projected"] == Decimal("50000.10")
    assert payer["crosses"] is True
    assert payer["tds_estimate"] == Decimal("5000.01")
    assert body["totals"] == {
        "interest_to_date": Decimal("50000.10"),  # paid on 1 Sep 2026, before today
        "interest_projected": Decimal("50000.10"),
        "tds_estimate": Decimal("5000.01"),
    }


def test_to_date_counts_only_what_is_paid_by_today():
    body = overview(groups_of(item(1, "Some Bank", 100000, start="2026-01-01", years=2)))
    # Yearly payout of 10,000 on 1 Jan 2027 only: nothing yet, 10,000 projected.
    payer = body["payers"][0]
    assert (payer["interest_to_date"], payer["interest_projected"]) == (0, Decimal("10000.00"))


def test_company_threshold_is_10000_for_nbfc_and_hfc():
    # 100,000 at 10% yearly payout falls on 1 Sep 2026 = 10,000 exactly; 100,001 crosses.
    body = overview(
        groups_of(
            item(1, "Bajaj Finance", 100000, issuer_id=3),
            item(2, "Other Co", 100001, issuer_id=2),
        ),
        MASTERS,
    )
    by_name = {p["name"]: p for p in body["payers"]}
    # The HFC is merged into HDFC Bank, so it takes the surviving bank's threshold.
    assert by_name["HDFC Bank"]["kind"] == "bank" and by_name["HDFC Bank"]["threshold"] == 50000
    bajaj = by_name["Bajaj Finance"]
    assert (bajaj["kind"], bajaj["threshold"], bajaj["crosses"]) == ("company", 10000, False)
    hfc_only = overview(groups_of(item(1, "Own HFC", 100001, issuer_id=4)), {
        4: SimpleNamespace(name="Own HFC", short_name=None, category="hfc", merged_into_id=None)
    })  # fmt: skip
    payer = hfc_only["payers"][0]
    assert (payer["kind"], payer["threshold"], payer["crosses"]) == ("company", 10000, True)
    assert payer["tds_estimate"] == Decimal("1000.01")


def test_manual_bank_names_group_case_and_space_insensitively():
    body = overview(
        groups_of(
            item(1, "Local Co-op Bank", 30000, label="A"),
            item(2, " local  co-op bank ", 20000, label="B"),
            item(3, "Elsewhere Bank", 10000),
        )
    )
    assert [(p["key"], p["name"]) for p in body["payers"]] == [
        ("name:local co-op bank", "Local Co-op Bank"),
        ("name:elsewhere bank", "Elsewhere Bank"),
    ]
    local = body["payers"][0]
    assert local["interest_projected"] == Decimal("5000.00")
    assert [(h["id"], h["name"]) for h in local["holdings"]] == [(1, "A"), (2, "B")]


def test_issuer_and_merged_issuer_roll_into_one_payer_and_name_matches_issuer():
    body = overview(
        groups_of(
            item(1, "HDFC Bank", 100000, issuer_id=1, label="Joint"),
            item(2, "HDFC Ltd", 100000, issuer_id=2),
            item(3, "hdfc bank limited", 100000),  # no issuer id: matched by name
        ),
        MASTERS,
    )
    assert [(p["key"], p["interest_projected"]) for p in body["payers"]] == [
        ("issuer:1", Decimal("30000.00"))
    ]
    names = [h["name"] for h in body["payers"][0]["holdings"]]
    assert sorted(names) == ["HDFC Ltd", "Joint", "hdfc bank limited"]  # label, else the bank name


def test_payers_without_interest_in_the_year_are_left_out_and_sorted_by_projected():
    body = overview(
        groups_of(
            item(1, "Small", 10000),
            item(2, "Big", 90000),
            item(3, "Past", 100000, start="2023-01-01", years=1),  # matured long ago
        )
    )
    assert [p["name"] for p in body["payers"]] == ["Big", "Small"]
    assert overview(groups_of(item(3, "Past", 100000, start="2023-01-01", years=1)))["payers"] == []


def test_last_year_has_to_date_equal_to_projected():
    body = overview(groups_of(item(1, "Some Bank", 100000, start="2024-09-01", years=3)), fy=2025)
    payer = body["payers"][0]
    assert body["fy"] == "2025-26" and body["is_current"] is False
    assert (body["fy_start"], body["fy_end"]) == (date(2025, 4, 1), date(2026, 3, 31))
    assert payer["interest_to_date"] == payer["interest_projected"] == Decimal("10000.00")


def test_matured_deposits_still_count_for_the_year_they_matured_in():
    matured = item(1, "Some Bank", 100000, start="2026-05-01", years=0, tenure_months=3,
                   compounding="simple", payout="cumulative", status="matured")  # fmt: skip
    payer = overview(groups_of(matured))["payers"][0]
    assert payer["interest_projected"] == Decimal(str(round(100000 * 0.10 * 92 / 365, 2)))


def test_savings_estimate_counts_only_savings_accounts_with_a_rate():
    cash = [
        {"id": 1, "kind": "savings", "interest_rate": 3, "balance": 100000},
        {"id": 2, "kind": "savings", "interest_rate": None, "balance": 50000},
        {"id": 3, "kind": "current", "interest_rate": 2, "balance": 50000},
        {"id": 4, "kind": "savings", "interest_rate": 4, "balance": 50000},
    ]
    body = overview(groups_of(cash=cash, bonds=3))
    assert body["savings"] == {"interest_estimate": Decimal("5000.00"), "accounts": 2}
    assert body["excluded"] == {"bonds": 3}
    assert body["payers"] == []
    assert body["totals"] == {
        "interest_to_date": 0, "interest_projected": 0, "tds_estimate": 0,
    }  # fmt: skip
    assert overview(groups_of())["savings"] is None


# --- Endpoint ----------------------------------------------------------------------------------


class _FixedDate(date):
    @classmethod
    def today(cls):
        return API_TODAY


@pytest.fixture
def tax_today(monkeypatch):
    monkeypatch.setattr(tax_router, "date", _FixedDate)


def _get(client, headers, **params):
    return client.get("/api/analytics/tax", headers=headers, params=params)


def test_requires_bearer(client):
    assert client.get("/api/analytics/tax").status_code == 401


def test_fy_param_accepts_current_and_previous_only(client, seeded, tax_today):  # noqa: F811
    assert _get(client, seeded[0], fy=2026).json()["fy"] == "2026-27"
    assert _get(client, seeded[0], fy=2025).json()["fy"] == "2025-26"
    for bad in (2024, 2027):
        response = _get(client, seeded[0], fy=bad)
        assert response.status_code == 422
        body = response.json()
        assert body["message"] == "Invalid financial year"
        assert body["description"] == "Choose 2026-27 (this year) or 2025-26 (last year)."
    assert _get(client, seeded[0], fy="abc").status_code == 422


def test_endpoint_shape_scoping_and_figures(client, seeded, tax_today, auth_engine, users):  # noqa: F811
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add(
            Cash(user_id=users[1], name="Interest account", kind="savings", balance=100000,
                 interest_rate=3, balance_date=API_TODAY)
        )  # fmt: skip
        session.commit()
    body = _get(client, seeded[0]).json()
    assert body["as_of"] == "2026-11-02" and body["is_current"] is True
    assert (body["fy"], body["fy_start"], body["fy_end"]) == ("2026-27", "2026-04-01", "2027-03-31")
    assert [f["label"] for f in body["available_fys"]] == ["2026-27", "2025-26"]
    assert body["excluded"] == {"bonds": 3}
    assert body["savings"] == {"interest_estimate": 3000, "accounts": 1}

    payers = {p["key"]: p for p in body["payers"]}
    assert set(payers) == {"issuer:1", "issuer:3", "name:local co-op bank", "issuer:4"}
    # Suryoday payout FD (matched by name): 4,000 each on 2 Jun, 2 Sep, 2 Dec 2026; 8,000 by now.
    assert (payers["issuer:3"]["interest_to_date"], payers["issuer:3"]["interest_projected"]) == (
        8000, 12000
    )
    # HDFC Bank cumulative FD from today plus the merged HDFC Ltd payout FD (6,000 on 2 Feb 2027).
    hdfc = payers["issuer:1"]
    assert [(h["type"], h["name"]) for h in hdfc["holdings"]][-1] == ("fd", "HDFC Ltd")
    assert hdfc["holdings"][-1]["interest_projected"] == 6000
    assert hdfc["interest_projected"] == pytest.approx(sum(h["interest_projected"] for h in hdfc["holdings"]))
    assert [p["interest_projected"] for p in body["payers"]] == sorted(
        (p["interest_projected"] for p in body["payers"]), reverse=True
    )
    # The soft-deleted 777,000 FD and user B's FD never appear.
    assert all(h["name"] != "Deleted" for p in body["payers"] for h in p["holdings"])
    assert all(p["interest_projected"] < 40000 for p in body["payers"])
    assert body["totals"]["interest_projected"] == pytest.approx(
        sum(p["interest_projected"] for p in body["payers"])
    )
    assert {p["kind"] for p in body["payers"]} == {"bank"}
