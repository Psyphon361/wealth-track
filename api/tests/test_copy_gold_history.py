from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql

from app.jobs import copy_gold_history as cgh


def _row(metal, purity, d, rate="100.00"):
    return {"metal": metal, "purity": purity, "rate_date": d, "rate_per_gram": Decimal(rate)}


def test_statement_is_insert_on_conflict_do_nothing():
    sql = str(cgh.build_insert_statement().compile(dialect=postgresql.dialect()))
    assert sql.startswith("INSERT INTO gold_rate_history")
    assert "ON CONFLICT (metal, purity, rate_date) DO NOTHING" in sql
    assert "DO UPDATE" not in sql


def test_batches_split_by_size():
    rows = [_row("gold", "999", date(2020, 1, 1))] * 2500
    sizes = [len(b) for b in cgh.batches(rows)]
    assert sizes == [1000, 1000, 500]
    assert list(cgh.batches([])) == []


def test_missing_rows_is_set_difference_on_keys():
    a = _row("gold", "999", date(2020, 1, 1))
    b = _row("gold", "999", date(2020, 1, 2))
    c = _row("silver", "999", date(2021, 5, 5))
    target = {cgh.row_key(a)}
    # a differing rate on an existing key is not copied (never updates)
    a_other = _row("gold", "999", date(2020, 1, 1), "999.00")
    assert cgh.missing_rows([a_other, b, c], target) == [b, c]


def test_counts_by_year_sorted():
    rows = [
        _row("gold", "999", date(2021, 1, 1)),
        _row("gold", "999", date(2020, 1, 1)),
        _row("gold", "995", date(2021, 1, 1)),
    ]
    assert cgh.counts_by_year(rows) == {2020: 1, 2021: 2}


def test_urls_equal_ignores_whitespace():
    assert cgh.urls_equal("postgresql://x/db", " postgresql://x/db\n")
    assert not cgh.urls_equal("postgresql://x/db", "postgresql://y/db")


def test_main_refuses_same_url(monkeypatch, capsys):
    secret = "postgresql://user:pw@host/db"
    monkeypatch.setenv("SOURCE_DATABASE_URL", secret)
    monkeypatch.setenv("TARGET_DATABASE_URL", secret)
    monkeypatch.setattr("sys.argv", ["copy_gold_history"])
    monkeypatch.setattr(cgh, "_engine", lambda url: pytest.fail("must not connect"))
    with pytest.raises(SystemExit) as exc:
        cgh.main()
    assert "same database" in str(exc.value.code)
    assert "pw" not in str(exc.value.code)
