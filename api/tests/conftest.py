import os
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

# Importing app modules must never connect; the engine is lazy, this is only a safety net.
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:1/dummy")

_STAMP = datetime(2025, 1, 1)
_ids = iter(range(1, 10_000))


def _base(**fields):
    return SimpleNamespace(
        id=next(_ids), created_at=_STAMP, updated_at=_STAMP, notes=None, **fields
    )


def make_fd(**kw):
    from datetime import date

    fields = dict(
        bank="Test Bank", label=None, principal=Decimal("100000"), rate=Decimal("7"),
        start_date=date(2025, 10, 24), compounding="quarterly", payout_type="cumulative",
        tenure_years=1, tenure_months=0, tenure_days=0,
    )  # fmt: skip
    fields.update(kw)
    return _base(**fields)


def make_stock(**kw):
    from datetime import date

    fields = dict(
        name="Test Stock", symbol=None, exchange="NSE", broker=None, quantity=10,
        avg_buy_price=Decimal("100"), buy_date=date(2025, 1, 1),
    )  # fmt: skip
    fields.update(kw)
    return _base(**fields)


def make_bond(**kw):
    from datetime import date

    fields = dict(
        name="Test Bond", isin=None, issuer="Issuer", bond_type="corporate",
        platform=None, quantity=10, face_value=Decimal("1000"),
        purchase_price=Decimal("1000"), purchase_date=date(2025, 10, 24),
        ytm=Decimal("8"), maturity_date=date(2026, 10, 24),
    )  # fmt: skip
    fields.update(kw)
    return _base(**fields)
