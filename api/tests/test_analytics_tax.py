"""Tax tab maths (services/analytics_tax.py) and GET /api/analytics/tax. Expected figures are
hand-worked from the rules in the module docstring; `today` is 2026-11-04 unless stated.

A financial year window is (31 Mar before, 31 Mar end]: 365 days, e.g. FY 2026-27 is
(2026-03-31, 2027-03-31].
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import text
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


# --- Bond coupons ------------------------------------------------------------------------------


def bond(id_=1, *, name="Bond", issuer="Acme Capital", bond_type="corporate", master_id=1,
         quantity=5, face_value=10000, purchase=date(2025, 1, 1), maturity=date(2027, 9, 30)):  # fmt: skip
    return {
        "id": id_, "name": name, "issuer": issuer, "bond_type": bond_type, "master_id": master_id,
        "quantity": quantity, "face_value": face_value, "purchase_date": purchase,
        "maturity_date": maturity,
    }  # fmt: skip


def bmaster(*, rate=9.5, frequency="monthly", bond_type="corporate", issuer="Acme Capital Ltd",
            face=10000, coupon_type="simple", issue_date=None, issue_price=None):  # fmt: skip
    return SimpleNamespace(
        coupon_rate=rate, interest_frequency=frequency, bond_type=bond_type, issuer=issuer,
        face_value=face, coupon_type=coupon_type, issue_date=issue_date, issue_price=issue_price,
    )  # fmt: skip


def coupons(holding, master, window=FY26):
    return tax.bond_coupons(holding, master, *window)


def test_monthly_coupon_is_face_times_quantity_times_rate_over_twelve():
    # 5 x 10,000 at 9.5% = 395.8333 a month; 12 payments on the 30th (28 Feb) in FY 2026-27.
    assert coupons(bond(), bmaster()) == pytest.approx(Decimal(12) * Decimal("395.8333333"))
    assert round(coupons(bond(), bmaster()), 2) == Decimal("4750.00")
    # 30 Apr to 30 Oct 2026 are paid by 4 Nov: 7 coupons.
    assert coupons(bond(), bmaster(), (FY26[0], TODAY)) == pytest.approx(
        7 * Decimal("395.8333333")
    )


def test_coupon_dates_clamp_to_the_end_of_the_month():
    holding = bond(maturity=date(2026, 5, 31), purchase=date(2025, 1, 1))
    one = Decimal("395.8333333")
    # Dates step back from 31 May: 30 Apr, 31 Mar, 28 Feb, 31 Jan ...
    assert coupons(holding, bmaster(), (date(2026, 2, 1), date(2026, 2, 28))) == pytest.approx(one)
    assert coupons(holding, bmaster(), (date(2026, 2, 1), date(2026, 2, 27))) == 0
    assert coupons(holding, bmaster(), (date(2026, 2, 28), date(2026, 3, 31))) == pytest.approx(one)
    # FY 2025-26 holds 30 Apr 2025 to 31 Mar 2026: 12 coupons.
    assert coupons(holding, bmaster(), FY25) == pytest.approx(12 * one)


def test_quarterly_half_yearly_and_yearly_coupons():
    # 100,000 face: 8% quarterly = 2,000 on 15 Mar, Jun, Sep, Dec.
    quarterly = bond(quantity=100, face_value=1000, maturity=date(2027, 12, 15))
    master = bmaster(rate=8, frequency="quarterly")
    assert coupons(quarterly, master) == 8000  # 15 Jun, 15 Sep, 15 Dec 2026, 15 Mar 2027
    assert coupons(quarterly, master, (FY26[0], TODAY)) == 4000  # 15 Jun and 15 Sep
    half = bond(quantity=100, face_value=1000, maturity=date(2027, 2, 10))
    master = bmaster(rate=5, frequency="half_yearly")
    assert coupons(half, master) == 5000  # 10 Aug 2026 and 10 Feb 2027
    assert coupons(half, master, FY25) == 5000  # 10 Aug 2025 and 10 Feb 2026
    yearly = bond(quantity=100, face_value=1000, maturity=date(2027, 3, 31))
    master = bmaster(rate=7, frequency="yearly")
    assert coupons(yearly, master) == 7000
    assert coupons(yearly, master, FY25) == 7000


def test_coupons_before_the_purchase_date_are_not_counted():
    holding = bond(purchase=date(2026, 10, 15))
    # 30 Oct 2026 to 30 Mar 2027 (28 Feb): 6 coupons; the 30 Sep one was before the purchase.
    assert coupons(holding, bmaster()) == pytest.approx(6 * Decimal("395.8333333"))
    assert coupons(bond(purchase=date(2026, 6, 1), maturity=date(2027, 3, 31)),
                   bmaster(frequency="yearly"), FY25) == 0  # fmt: skip


def test_coupons_stop_at_maturity():
    holding = bond(maturity=date(2026, 8, 31))
    # 30 Apr, 31 May, 30 Jun, 31 Jul, 31 Aug 2026.
    assert coupons(holding, bmaster()) == pytest.approx(5 * Decimal("395.8333333"))
    assert coupons(holding, bmaster(), (date(2026, 8, 31), date(2027, 3, 31))) == 0


def test_on_maturity_bond_pays_all_interest_on_the_maturity_date():
    holding = bond(quantity=100, face_value=1000, maturity=date(2027, 1, 1))
    master = bmaster(rate=9, frequency="on_maturity", issue_date=date(2024, 4, 1))
    t = valuation._year_fraction(date(2024, 4, 1), date(2027, 1, 1))
    assert coupons(holding, master) == pytest.approx(Decimal(100000 * 0.09 * t))
    assert coupons(holding, master, FY25) == 0
    assert coupons(holding, master, (FY26[0], TODAY)) == 0  # not paid yet
    compounding = bmaster(rate=9, frequency="on_maturity", issue_date=date(2024, 4, 1),
                          coupon_type="compounding")  # fmt: skip
    assert coupons(holding, compounding) == pytest.approx(Decimal(100000 * (1.09**t - 1)))
    no_issue = bmaster(rate=9, frequency="on_maturity")
    assert coupons(holding, no_issue) is None


def test_sgb_pays_two_and_a_half_percent_half_yearly_on_the_issue_price_per_gram():
    holding = bond(bond_type="sgb", quantity=5, face_value=None, maturity=date(2027, 6, 1),
                   purchase=date(2026, 8, 1))  # fmt: skip
    master = bmaster(rate=2.5, frequency=None, bond_type="sgb", face=None, issue_price=6000)
    # 5 g x 6,000 x 2.5% / 2 = 375 on 1 Dec 2026 (1 Jun 2027 is after the year).
    assert coupons(holding, master) == 375
    assert coupons(holding, master, (date(2027, 3, 31), date(2028, 3, 31))) == 375
    assert coupons(holding, bmaster(rate=2.5, frequency=None, bond_type="sgb", face=None)) is None


def test_bonds_without_usable_coupon_data_return_none():
    assert coupons(bond(), None) is None
    assert coupons(bond(), bmaster(rate=None)) is None
    assert coupons(bond(), bmaster(frequency="none")) is None
    assert coupons(bond(), bmaster(frequency="irregular")) is None
    assert coupons(bond(), bmaster(frequency=None)) is None
    assert coupons(bond(face_value=None), bmaster(face=None)) is None
    # Face value falls back to the master's.
    assert coupons(bond(face_value=None), bmaster()) is not None


def bond_overview(*bonds, masters=None, cash=(), pf=(), fy=None):
    groups = groups_of(cash=cash)
    groups[2]["items"] = list(bonds)
    groups.append({"type": "pf", "items": list(pf)})
    return tax.tax_overview(groups, {}, TODAY, fy, masters or {})


def test_bond_payer_is_one_per_issuer_with_the_10000_threshold():
    masters = {1: bmaster(rate=10, frequency="yearly", face=1000), 2: bmaster(rate=10.001, frequency="yearly", face=1000, issuer="Other Capital")}  # fmt: skip
    first = bond(1, quantity=100, face_value=1000, maturity=date(2027, 3, 31), name="NCD A")
    second = bond(2, quantity=100, face_value=1000, maturity=date(2027, 3, 31), master_id=2, name="NCD B")  # fmt: skip
    twin = bond(3, quantity=100, face_value=1000, maturity=date(2027, 3, 31), master_id=1, name="NCD C", issuer="acme  capital ltd")  # fmt: skip
    body = bond_overview(first, second, twin, masters=masters)
    by_key = {p["key"]: p for p in body["payers"]}
    assert set(by_key) == {"bond:acme capital ltd", "bond:other capital"}
    exact = by_key["bond:acme capital ltd"]
    assert exact["kind"] == "bond" and exact["threshold"] == 10000
    # Two NCDs of the issuer: 10,000 each = 20,000, over the threshold.
    assert exact["interest_projected"] == Decimal("20000.00") and exact["crosses"] is True
    assert exact["tds_estimate"] == Decimal("2000.00")
    assert [(h["type"], h["name"]) for h in exact["holdings"]] == [("bond", "NCD A"), ("bond", "NCD C")]
    single = by_key["bond:other capital"]
    assert single["interest_projected"] == Decimal("10001.00") and single["crosses"] is True
    assert single["tds_estimate"] == Decimal("1000.10")
    assert body["totals"]["tds_estimate"] == Decimal("3000.10")
    # Exactly 10,000 does not cross.
    body = bond_overview(first, masters=masters)
    assert body["payers"][0]["interest_projected"] == Decimal("10000.00")
    assert body["payers"][0]["crosses"] is False and body["payers"][0]["tds_estimate"] == 0


def test_government_bonds_and_sgbs_have_no_threshold_and_no_tds():
    gsec = bond(1, bond_type="government", quantity=100, face_value=1000, maturity=date(2027, 3, 31), issuer="Govt")  # fmt: skip
    sgb = bond(2, bond_type="sgb", quantity=5000, face_value=None, master_id=2, maturity=date(2027, 6, 1), name="SGB", purchase=date(2026, 8, 1))  # fmt: skip
    masters = {
        1: bmaster(rate=40, frequency="yearly", face=1000, bond_type="government", issuer="Government of India"),
        2: bmaster(rate=2.5, frequency=None, bond_type="sgb", face=None, issuer="Government of India", issue_price=6000),
    }  # fmt: skip
    body = bond_overview(gsec, sgb, masters=masters)
    (payer,) = body["payers"]
    assert payer["key"] == "bond:government of india" and payer["threshold"] is None
    # 40,000 + 5,000 g x 6,000 x 2.5% / 2 = 375,000 (1 Dec 2026), far over any threshold, no TDS.
    assert payer["interest_projected"] == Decimal("415000.00")
    assert payer["crosses"] is False and payer["tds_estimate"] == 0
    assert body["totals"]["tds_estimate"] == 0


def test_tax_free_bonds_go_to_tax_free_not_payers():
    holding = bond(bond_type="tax_free", quantity=100, face_value=1000, maturity=date(2027, 1, 15), name="NHAI 2027")  # fmt: skip
    body = bond_overview(holding, masters={1: bmaster(rate=8, frequency="yearly", bond_type="tax_free", face=1000)})  # fmt: skip
    assert body["payers"] == []
    assert body["totals"]["interest_projected"] == 0
    assert body["tax_free"] == {
        "interest_to_date": 0,
        "interest_projected": Decimal("8000.00"),
        "items": [{"kind": "tax_free_bond", "id": 1, "name": "NHAI 2027",
                   "interest_to_date": 0, "interest_projected": Decimal("8000.00")}],
    }  # fmt: skip
    assert body["taxable"] == {"interest_to_date": 0, "interest_projected": 0}


def test_excluded_bonds_count_only_those_without_coupon_data():
    usable = bond(1)
    no_master = bond(2, master_id=None)
    no_rate = bond(3, master_id=2)
    paid_off = bond(4, maturity=date(2026, 1, 31))  # usable, but nothing falls in FY 2026-27
    masters = {1: bmaster(), 2: bmaster(rate=None)}
    body = bond_overview(usable, no_master, no_rate, paid_off, masters=masters)
    assert body["excluded"] == {"bonds": 2}
    assert [h["id"] for p in body["payers"] for h in p["holdings"]] == [1]


def pf_item(id_, kind, balance, rate, balance_date, name=None):
    return {"id": id_, "kind": kind, "name": name or kind.upper(), "balance": balance,
            "interest_rate": rate, "balance_date": balance_date}  # fmt: skip


def test_pf_interest_is_tax_free_and_starts_at_the_balance_date():
    ppf = pf_item(1, "ppf", 100000, 7.1, "2026-10-01", "My PPF")
    body = bond_overview(pf=[ppf])
    (entry,) = body["tax_free"]["items"]
    assert (entry["kind"], entry["id"], entry["name"]) == ("ppf", 1, "My PPF")
    # 1 Oct 2026 to 31 Mar 2027 is 181 days; to 4 Nov 2026 is 34 days.
    assert entry["interest_projected"] == Decimal(str(round(100000 * 0.071 * 181 / 365, 2)))
    assert entry["interest_to_date"] == Decimal(str(round(100000 * 0.071 * 34 / 365, 2)))
    assert body["payers"] == [] and body["savings"] is None
    # Balance dated after the year: nothing in it; dated before it: the whole year.
    assert bond_overview(pf=[ppf], fy=2025)["tax_free"]["items"] == []
    old = pf_item(2, "epf", 100000, 8.25, "2025-01-01")
    full = bond_overview(pf=[old], fy=2025)["tax_free"]
    assert full["interest_projected"] == full["interest_to_date"] == Decimal("8250.00")
    assert full["items"][0]["kind"] == "epf"
    assert bond_overview(pf=[pf_item(3, "vpf", 1000, 0, "2025-01-01")])["tax_free"]["items"] == []


def test_taxable_and_tax_free_totals_add_up_across_sources():
    fd_item = item(1, "Some Bank", 100000, rate=10, start="2026-04-01", years=1,
                   compounding="simple", payout="cumulative")  # fmt: skip
    cash = [{"id": 1, "kind": "savings", "interest_rate": 3, "balance": 100000}]
    ncd = bond(7, quantity=100, face_value=1000, maturity=date(2027, 3, 31))
    groups = groups_of(fd_item, cash=cash)
    groups[2]["items"] = [ncd]
    groups.append({"type": "pf", "items": [pf_item(1, "ppf", 100000, 7.1, "2025-01-01")]})
    body = tax.tax_overview(groups, {}, TODAY, None, {1: bmaster(rate=7, frequency="yearly", face=1000)})
    payers_to_date = sum(p["interest_to_date"] for p in body["payers"])
    payers_projected = sum(p["interest_projected"] for p in body["payers"])
    assert payers_projected == body["totals"]["interest_projected"]
    savings_to_date = Decimal(str(round(100000 * 0.03 * 218 / 365, 2)))
    assert body["taxable"]["interest_projected"] == payers_projected + Decimal("3000.00")
    assert body["taxable"]["interest_to_date"] == payers_to_date + savings_to_date
    assert body["tax_free"]["interest_projected"] == Decimal("7100.00")
    assert body["tax_free"]["interest_to_date"] == Decimal(str(round(100000 * 0.071 * 218 / 365, 2)))
    assert {p["kind"] for p in body["payers"]} == {"bank", "bond"}


# --- Endpoint ----------------------------------------------------------------------------------


class _FixedDate(date):
    @classmethod
    def today(cls):
        return API_TODAY


@pytest.fixture
def tax_today(monkeypatch, seeded, auth_engine):  # noqa: F811
    monkeypatch.setattr(tax_router, "date", _FixedDate)
    # The shared fixture's bond_master has only id, bond_type and issuer; add the coupon columns.
    with auth_engine.begin() as conn:
        for column, kind in (
            ("face_value", "NUMERIC"), ("coupon_rate", "NUMERIC"), ("coupon_type", "VARCHAR"),
            ("interest_frequency", "VARCHAR"), ("issue_date", "DATE"), ("issue_price", "NUMERIC"),
        ):  # fmt: skip
            conn.execute(text(f"ALTER TABLE bond_master ADD COLUMN {column} {kind}"))


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
    assert body["taxable"]["interest_projected"] == pytest.approx(
        body["totals"]["interest_projected"] + 3000
    )
    # PPF 200,000 at 7.1% and EPF 100,000 at 8.25% from their balance date (2 Nov) to 31 Mar: 149 days.
    assert [(i["kind"], i["name"], i["interest_to_date"], i["interest_projected"])
            for i in body["tax_free"]["items"]] == [
        ("ppf", "PPF", 0, 5796.71), ("epf", "Employer EPF", 0, 3367.81)
    ]  # fmt: skip
    assert (body["tax_free"]["interest_to_date"], body["tax_free"]["interest_projected"]) == (
        0, pytest.approx(9164.52)
    )


def test_endpoint_bond_coupons_from_the_linked_master(client, seeded, tax_today, auth_engine):  # noqa: F811
    with auth_engine.begin() as conn:
        # NHAI (tax-free, 10 x 1,000, matures 15 Jan 2027) and the SGB (5 g, matures 1 Jun 2027).
        conn.execute(text(
            "UPDATE bond_master SET coupon_rate = 8, interest_frequency = 'yearly', face_value = 1000 "
            "WHERE id = 1"
        ))  # fmt: skip
        conn.execute(text(
            "UPDATE bond_master SET coupon_rate = 2.5, issue_price = 6000 WHERE id = 2"
        ))  # fmt: skip
    body = _get(client, seeded[0]).json()
    # NHAI: 10 x 1,000 x 8% = 800 on 15 Jan 2027; a tax-free bond is not a payer.
    (nhai,) = [i for i in body["tax_free"]["items"] if i["kind"] == "tax_free_bond"]
    assert (nhai["name"], nhai["interest_to_date"], nhai["interest_projected"]) == (
        "NHAI 2030", 0, 800
    )
    # SGB: 5 g x 6,000 x 2.5% / 2 = 375 on 1 Dec 2026; no TDS.
    (payer,) = [p for p in body["payers"] if p["kind"] == "bond"]
    assert (payer["name"], payer["threshold"], payer["crosses"]) == ("Government of India", None, False)
    assert payer["interest_projected"] == 375 and payer["tds_estimate"] == 0
    assert payer["holdings"][0]["type"] == "bond"
    assert body["excluded"] == {"bonds": 1}  # Old Bond has no linked master
