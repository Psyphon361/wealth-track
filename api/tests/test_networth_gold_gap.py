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


def test_rate_eight_days_old_after_latest_rate_is_carried_forward():
    result = gold_history({("gold", "916"): [(RATE_DAY, Decimal("5100"))]})
    assert current_on(result, "2026-10-18") == Decimal("51000.00")
    assert current_on(result, "2026-10-30") == Decimal("51000.00")


def test_gap_between_two_rates_over_seven_days_falls_back_to_cost():
    rates = {
        ("gold", "916"): [
            (date(2026, 10, 3), Decimal("5000")),
            (date(2026, 10, 25), Decimal("5200")),
        ]
    }
    result = gold_history(rates)
    assert current_on(result, "2026-10-10") == Decimal("50000.00")
    assert current_on(result, "2026-10-11") == Decimal("50000.00")
    assert current_on(result, "2026-10-25") == Decimal("52000.00")
    assert current_on(result, "2026-10-30") == Decimal("52000.00")


def test_date_before_first_rate_falls_back_to_cost():
    result = gold_history({("gold", "916"): [(date(2026, 10, 20), Decimal("5100"))]})
    assert current_on(result, "2026-10-19") == Decimal("50000.00")
    assert current_on(result, "2026-10-20") == Decimal("51000.00")


def test_carry_forward_is_per_metal_and_purity():
    result = gold_history({("gold", "999"): [(RATE_DAY, Decimal("6000"))]})
    assert current_on(result, "2026-10-25") == Decimal("50000.00")


def test_silver_925_series_is_carried_forward_like_gold():
    silver = make_gold(
        metal="silver", purity="925", purchase_date=date(2026, 10, 1),
        weight_grams=Decimal("100"), invested_amount=Decimal("8000"),
    )  # fmt: skip
    result = networth.build_history(
        "1m", TODAY, {"gold": [silver]}, {}, {}, {}, (Decimal("0"), Decimal("0")),
        {("silver", "925"): [(RATE_DAY, Decimal("90"))]},
    )  # fmt: skip
    assert current_on(result, "2026-10-30") == Decimal("9000.00")


def test_no_rate_falls_back_to_cost():
    result = gold_history({})
    assert current_on(result, "2026-10-20") == Decimal("50000.00")


def test_on_or_before_without_limit_ignores_age():
    series = [(date(2018, 2, 1), Decimal("2800"))]
    assert networth.on_or_before(series, date(2019, 6, 1)) == Decimal("2800")
    assert networth.on_or_before(series, date(2019, 6, 1), 7) is None
