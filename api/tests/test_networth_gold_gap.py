from datetime import date
from decimal import Decimal

from app.services import networth
from tests.conftest import make_gold

TODAY = date(2026, 10, 31)
RATE_DAY = date(2026, 10, 10)


def gold_history(rates):
    gold = make_gold(
        purchase_date=date(2026, 10, 1), weight_grams=Decimal("10"),
        invested_amount=Decimal("50000"), purity="916",
    )  # fmt: skip
    return networth.build_history(
        "1m", TODAY, {"gold": [gold]}, {}, {}, {}, (Decimal("0"), Decimal("0")), rates
    )


def current_on(result, day):
    return next(p for p in result["points"] if p["date"] == day)["current"]


def test_rate_exactly_seven_days_old_is_used():
    result = gold_history({("gold", "916"): [(RATE_DAY, Decimal("5100"))]})
    assert current_on(result, "2026-10-17") == Decimal("51000.00")


def test_rate_eight_days_old_falls_back_to_cost():
    result = gold_history({("gold", "916"): [(RATE_DAY, Decimal("5100"))]})
    assert current_on(result, "2026-10-18") == Decimal("50000.00")


def test_no_rate_falls_back_to_cost():
    result = gold_history({})
    assert current_on(result, "2026-10-20") == Decimal("50000.00")


def test_on_or_before_without_limit_ignores_age():
    series = [(date(2018, 2, 1), Decimal("2800"))]
    assert networth.on_or_before(series, date(2019, 6, 1)) == Decimal("2800")
    assert networth.on_or_before(series, date(2019, 6, 1), 7) is None
