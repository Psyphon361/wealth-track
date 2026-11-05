from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import NpsMaster
from app.services import duplicates, nps
from tests.test_scoping import client, users  # noqa: F401  (fixtures)

FD = {
    "bank": "SBI", "label": "FD", "principal": 100000, "rate": 7, "start_date": "2026-03-12",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
RD = {
    "bank": "HDFC Bank", "monthly_instalment": 5000, "rate": 6.5, "start_date": "2026-01-05",
    "compounding": "quarterly", "tenure_years": 2,
}  # fmt: skip
STOCK = {
    "name": "Acme Ltd", "exchange": "NSE", "quantity": 10, "avg_buy_price": 100,
    "buy_date": "2025-01-01",
}  # fmt: skip
BOND = {
    "name": "Acme 2030 bond", "isin": "INE002A07012", "issuer": "Acme Ltd", "bond_type": "corporate",
    "quantity": 5, "purchase_price": 1000, "invested_amount": 5000, "purchase_date": "2025-01-01",
    "ytm": 8, "maturity_date": "2030-01-01",
}  # fmt: skip
MF = {
    "scheme_name": "Acme Equity Fund", "category": "equity", "units": 100, "avg_nav": 50,
    "invested_amount": 5000, "purchase_date": "2025-02-01",
}  # fmt: skip
NPS = {"scheme_id": "SM001003", "units": 1000, "contributed": 40000, "start_date": "2025-10-01"}
GOLD = {
    "name": "Necklace", "form": "jewellery", "metal": "gold", "purity": "916", "weight_grams": 25.5,
    "purchase_date": "2025-01-01", "invested_amount": 150000,
}  # fmt: skip
CASH = {
    "name": "HDFC savings", "kind": "savings", "balance": 25000, "interest_rate": 3.5,
    "balance_date": "2025-10-01",
}  # fmt: skip
PF = {
    "name": "Company EPF", "kind": "epf", "balance": 100000, "balance_date": "2025-10-01",
    "interest_rate": 8.25,
}  # fmt: skip
OTHER = {"name": "Bitcoin", "category": "Crypto", "current_value": 80000, "value_date": "2025-10-01"}

# slug, payload, a change that is still a duplicate, changes that are not
CASES = [
    ("fd", FD, {"bank": " sbi ", "rate": 8, "label": "Other"}, [{"bank": "HDFC Bank"}, {"principal": 100001}, {"start_date": "2026-03-13"}]),
    ("rd", RD, {"bank": "hdfc bank", "rate": 7}, [{"bank": "SBI"}, {"monthly_instalment": 5001}, {"start_date": "2026-01-06"}]),
    ("stock", STOCK, {"name": "ACME LTD", "avg_buy_price": 120}, [{"name": "Other Ltd"}, {"quantity": 11}, {"buy_date": "2025-01-02"}]),
    ("bond", BOND, {"name": "acme 2030 BOND", "ytm": 9}, [{"name": "Acme 2031 bond"}, {"quantity": 6, "invested_amount": 6000}, {"purchase_date": "2025-01-02"}]),
    ("mf", MF, {"scheme_name": "acme equity fund", "avg_nav": 50}, [{"scheme_name": "Acme Debt Fund"}, {"units": 101, "invested_amount": 5050}, {"purchase_date": "2025-02-02"}]),
    ("nps", NPS, {"units": 1200, "contributed": 50000}, [{"scheme_id": "SM002005"}, {"start_date": "2025-10-02"}]),
    ("gold", GOLD, {"name": "Chain", "invested_amount": 160000}, [{"metal": "silver", "purity": "999"}, {"form": "coin"}, {"purity": "999"}, {"weight_grams": 25.6}, {"purchase_date": "2025-01-02"}]),
    ("cash", CASH, {"name": " hdfc SAVINGS", "balance": 1}, [{"name": "HDFC current"}, {"kind": "current"}]),
    ("pf", PF, {"name": "company epf", "balance": 5}, [{"name": "Other EPF"}, {"kind": "vpf"}]),
    ("other", OTHER, {"name": "bitcoin", "category": "CRYPTO", "current_value": 1}, [{"name": "Ether"}, {"category": "Property"}]),
]  # fmt: skip
IDS = [case[0] for case in CASES]


@pytest.fixture(autouse=True)
def nps_setup(monkeypatch, auth_engine, client):  # noqa: F811
    """NPS history sync is recorded, not fetched; two schemes in the (SQLite) master."""
    monkeypatch.setattr(nps, "sync_scheme_safely", lambda scheme_id: None)
    with sessionmaker(bind=auth_engine, expire_on_commit=False)() as session:
        session.add_all([
            NpsMaster(scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                      scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E"),
            NpsMaster(scheme_id="SM002005", pfm_code="PFM002", pfm_name="UTI Pension Fund",
                      scheme_name="UTI SCHEME G - TIER II", tier="II", asset_class="G"),
        ])
        session.commit()


def _post(client, slug, body, headers, confirm=False):
    url = f"/api/assets/{slug}" + ("?confirm_duplicate=true" if confirm else "")
    return client.post(url, json=body, headers=headers)


@pytest.mark.parametrize(("slug", "body", "same", "different"), CASES, ids=IDS)
def test_rule_matches_and_near_misses_do_not(client, users, slug, body, same, different):  # noqa: F811
    a = users[0]
    first = _post(client, slug, body, a)
    assert first.status_code == 201, first.text
    for change in different:
        response = _post(client, slug, {**body, **change}, a)
        assert response.status_code == 201, (change, response.text)
    response = _post(client, slug, {**body, **same}, a)
    assert response.status_code == 409, response.text
    assert [d["id"] for d in response.json()["duplicates"]] == [first.json()["id"]]


@pytest.mark.parametrize(("slug", "body"), [(c[0], c[1]) for c in CASES], ids=IDS)
def test_confirm_duplicate_creates(client, users, slug, body):  # noqa: F811
    a = users[0]
    assert _post(client, slug, body, a).status_code == 201
    assert _post(client, slug, body, a).status_code == 409
    assert _post(client, slug, body, a, confirm=True).status_code == 201
    assert len(client.get(f"/api/assets/{slug}", headers=a).json()) == 2


@pytest.mark.parametrize(("slug", "body"), [(c[0], c[1]) for c in CASES], ids=IDS)
def test_soft_deleted_holdings_are_ignored(client, users, slug, body):  # noqa: F811
    a = users[0]
    item_id = _post(client, slug, body, a).json()["id"]
    assert client.delete(f"/api/assets/{slug}/{item_id}", headers=a).status_code == 200
    assert _post(client, slug, body, a).status_code == 201


@pytest.mark.parametrize(("slug", "body"), [(c[0], c[1]) for c in CASES], ids=IDS)
def test_other_users_holdings_never_match(client, users, slug, body):  # noqa: F811
    a, _, b, _ = users
    assert _post(client, slug, body, a).status_code == 201
    assert _post(client, slug, body, b).status_code == 201


def test_409_body_shape(client, users):  # noqa: F811
    a = users[0]
    first = _post(client, "fd", FD, a).json()["id"]
    response = _post(client, "fd", FD, a)
    assert response.status_code == 409
    assert response.json() == {
        "message": "This looks like a holding you already have",
        "description": "SBI · FD · ₹1,00,000 from 12 Mar 2026 is already in your portfolio.",
        "duplicates": [{"id": first, "name": "SBI · FD"}],
    }


def test_409_with_several_matches_describes_the_first(client, users):  # noqa: F811
    a = users[0]
    first = _post(client, "cash", CASH, a).json()["id"]
    second = _post(client, "cash", CASH, a, confirm=True).json()["id"]
    response = _post(client, "cash", CASH, a)
    assert response.status_code == 409
    body = response.json()
    assert body["description"] == "HDFC savings · Savings account and 1 more are already in your portfolio."
    assert [d["id"] for d in body["duplicates"]] == [first, second]


def test_invalid_body_is_still_422(client, users):  # noqa: F811
    a = users[0]
    _post(client, "fd", FD, a)
    assert _post(client, "fd", {**FD, "principal": 0}, a).status_code == 422


def test_edit_is_not_checked(client, users):  # noqa: F811
    a = users[0]
    _post(client, "fd", FD, a)
    other = _post(client, "fd", {**FD, "principal": 5000}, a).json()["id"]
    assert client.put(f"/api/assets/fd/{other}", json=FD, headers=a).status_code == 200


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_stock_and_bond_match_on_master_when_both_linked():
    new = {"master_id": 7, "name": "Acme Ltd", "quantity": 10, "buy_date": date(2025, 1, 1)}
    same_master = _Row(master_id=7, name="Acme Limited", quantity=10, buy_date=date(2025, 1, 1))
    other_master = _Row(master_id=8, name="Acme Ltd", quantity=10, buy_date=date(2025, 1, 1))
    unlinked = _Row(master_id=None, name="acme ltd", quantity=10, buy_date=date(2025, 1, 1))
    assert duplicates._matches("stock", new, same_master)
    assert not duplicates._matches("stock", new, other_master)
    assert duplicates._matches("stock", new, unlinked)
    bond = {"master_id": 7, "name": "B", "quantity": 1, "purchase_date": date(2025, 1, 1)}
    assert duplicates._matches("bond", bond, _Row(master_id=7, name="X", quantity=1, purchase_date=date(2025, 1, 1)))
    assert not duplicates._matches("bond", bond, _Row(master_id=9, name="B", quantity=1, purchase_date=date(2025, 1, 1)))


def test_mf_matches_on_scheme_code_when_both_have_one():
    new = {"scheme_code": 100, "scheme_name": "A", "units": Decimal("10"), "purchase_date": date(2025, 1, 1)}
    row = {"scheme_name": "Renamed", "units": Decimal("10.000"), "purchase_date": date(2025, 1, 1)}
    assert duplicates._matches("mf", new, _Row(scheme_code=100, **row))
    assert not duplicates._matches("mf", new, _Row(scheme_code=101, **{**row, "scheme_name": "A"}))
    assert duplicates._matches("mf", {**new, "scheme_code": None}, _Row(scheme_code=None, **{**row, "scheme_name": "a"}))


def test_format_inr_uses_indian_grouping():
    assert duplicates.format_inr(Decimal("100000")) == "₹1,00,000"
    assert duplicates.format_inr(Decimal("5000")) == "₹5,000"
    assert duplicates.format_inr(Decimal("999")) == "₹999"
    assert duplicates.format_inr(Decimal("1234567.5")) == "₹12,34,567.50"
    assert duplicates.format_inr(Decimal("10000000")) == "₹1,00,00,000"
