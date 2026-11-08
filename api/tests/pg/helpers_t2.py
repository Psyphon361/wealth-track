"""Seed helpers and request bodies for the real-Postgres behaviour tests (P1-T2)."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models import FdIssuerMaster, MFMaster, MFNavHistory, MFNavHistorySync, NpsMaster

TODAY = date(2026, 3, 10)  # the fixed "today" of the SIP service in these tests
SELL_DAY = "2026-01-15"

STOCK = {
    "name": "Acme Ltd", "exchange": "NSE", "quantity": 100, "avg_buy_price": 50,
    "buy_date": "2025-01-01",
}  # fmt: skip
BOND = {
    "name": "Test Bond 2035", "issuer": "Test Issuer", "bond_type": "corporate", "quantity": 10,
    "face_value": 1000, "purchase_price": 1000, "invested_amount": 10000,
    "purchase_date": "2025-01-01", "ytm": 8, "maturity_date": "2035-01-01",
}  # fmt: skip
GOLD = {
    "name": "Coins", "form": "coin", "metal": "gold", "purity": "999", "weight_grams": 10,
    "purchase_date": "2025-01-01", "invested_amount": 50000,
}  # fmt: skip
OTHER = {
    "name": "Plot", "category": "Property", "current_value": 80000, "value_date": "2026-01-01",
    "invested_amount": 50000, "acquired_on": "2024-01-01",
}  # fmt: skip
CASH = {"name": "HDFC Savings", "kind": "savings", "balance": 1000, "balance_date": "2026-01-01"}
FD = {
    "bank": "Old Bank", "principal": 100000, "rate": 8, "start_date": "2024-01-01",
    "compounding": "quarterly", "payout_type": "cumulative", "tenure_years": 1,
}  # fmt: skip
RD = {
    "bank": "RD Bank", "monthly_instalment": 5000, "rate": 6, "start_date": "2024-01-01",
    "compounding": "quarterly", "tenure_years": 1,
}  # fmt: skip
MF = {
    "scheme_name": "Fund A", "scheme_code": 100, "platform": "Groww", "category": "equity",
    "units": 100, "avg_nav": 40, "invested_amount": 4000, "purchase_date": "2025-06-01",
}  # fmt: skip
NPS = {"scheme_id": "SM001003", "units": "1000.1234", "contributed": 40000, "start_date": "2025-10-01"}
SIP = {
    "scheme_code": 100, "platform": "Groww", "amount": 5000, "day_of_month": 5,
    "start_date": "2026-01-05", "include_past": True,
}  # fmt: skip
NONE = {"kind": "none"}


def seed_masters(session) -> int:
    """MF schemes 100 and 102 with daily NAV 50 and a fresh sync, an NPS scheme and an FD issuer.

    Returns the issuer id. Daily NAVs and a fresh MFNavHistorySync mean the SIP service never
    needs the network.
    """
    session.add_all(
        [
            MFMaster(scheme_code=100, name="Fund A - Direct Growth", category="equity", is_active=True),
            MFMaster(scheme_code=102, name="Fund C - Direct Growth", category="index", is_active=True),
            NpsMaster(
                scheme_id="SM001003", pfm_code="PFM001", pfm_name="SBI Pension Funds",
                scheme_name="SBI PENSION FUND SCHEME E - TIER I", tier="I", asset_class="E",
            ),
        ]
    )  # fmt: skip
    issuer = FdIssuerMaster(
        code="TESTBANK", name="Test Bank Limited", category="private_sector", sources=["seed"]
    )
    session.add(issuer)
    session.flush()  # the NAV rows below reference the schemes
    for code in (100, 102):
        day = date(2024, 12, 1)
        while day <= date(2026, 7, 31):
            session.add(MFNavHistory(scheme_code=code, nav_date=day, nav=Decimal("50")))
            day += timedelta(days=1)
        session.add(
            MFNavHistorySync(
                scheme_code=code, first_date=date(2024, 12, 1), last_date=date(2026, 7, 31),
                fetched_at=datetime.now(timezone.utc),
            )
        )  # fmt: skip
    session.commit()
    return issuer.id


def add(client, headers, slug, body, **params) -> int:
    response = client.post(f"/api/assets/{slug}", json=body, headers=headers, params=params)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def asset(client, headers, slug, item_id) -> dict:
    response = client.get(f"/api/assets/{slug}/{item_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()
