import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.exceptions import RequestValidationError

from app.services.nav_history import parse_mfapi, pick_on_or_before, validate_not_future

FIXTURE = Path(__file__).parent / "fixtures" / "mfapi_sample.json"


@pytest.fixture(scope="module")
def sample():
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def rows(sample):
    return parse_mfapi(sample)


def test_parse_fixture(sample, rows):
    assert len(rows) == len(sample["data"]) == 30
    assert rows[0] == (date(2026, 10, 23), Decimal("88.9695"))
    assert rows[-1] == (date(2026, 9, 9), Decimal("89.3946"))


def test_parse_skips_bad_rows():
    payload = {
        "data": [
            {"date": "23-10-2026", "nav": "88.9695"},
            {"date": "22-10-2026", "nav": "0"},
            {"date": "21-10-2026", "nav": "-3"},
            {"date": "20-10-2026", "nav": "N.A."},
            {"date": "19-10-2026", "nav": ""},
            {"date": "31-02-2026", "nav": "10"},
            {"date": "garbage", "nav": "10"},
            {"date": "18-10-2026"},
            "nonsense",
            {"date": "16-10-2026", "nav": "90.88440"},
        ]
    }
    assert parse_mfapi(payload) == [
        (date(2026, 10, 23), Decimal("88.9695")),
        (date(2026, 10, 16), Decimal("90.8844")),
    ]


@pytest.mark.parametrize("payload", [{}, {"data": []}, {"data": None}, None, [], "x"])
def test_parse_empty_or_malformed(payload):
    assert parse_mfapi(payload) == []


def test_pick_exact_date(rows):
    assert pick_on_or_before(rows, date(2026, 10, 15)) == (date(2026, 10, 15), Decimal("90.6040"))


@pytest.mark.parametrize("weekend_day", [date(2026, 10, 17), date(2026, 10, 18)])
def test_pick_weekend_gives_previous_friday(rows, weekend_day):
    assert pick_on_or_before(rows, weekend_day) == (date(2026, 10, 16), Decimal("90.8844"))


def test_pick_before_first_row_is_none(rows):
    assert pick_on_or_before(rows, date(2026, 9, 8)) is None


def test_pick_after_last_row_gives_last(rows):
    assert pick_on_or_before(rows, date(2030, 1, 1))[0] == date(2026, 10, 23)


def test_pick_empty_list_is_none():
    assert pick_on_or_before([], date(2026, 10, 15)) is None


def test_future_date_rejected():
    with pytest.raises(RequestValidationError) as info:
        validate_not_future(date(2026, 10, 26), today=date(2026, 10, 25))
    error = info.value.errors()[0]
    assert error["loc"] == ("query", "date")
    assert error["msg"] == "Date cannot be in the future"


def test_today_and_past_allowed():
    validate_not_future(date(2026, 10, 25), today=date(2026, 10, 25))
    validate_not_future(date(2000, 1, 1), today=date(2026, 10, 25))
