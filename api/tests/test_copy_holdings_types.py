import pytest

from app.jobs.copy_holdings import SLUGS, TABLES, select_tables


def test_absent_means_all():
    assert select_tables(None) == TABLES


def test_valid_subset_keeps_tables_order():
    got = select_tables("pf, fd,stock")
    assert [s.model for s in got] == [SLUGS["fd"], SLUGS["stock"], SLUGS["pf"]]


def test_every_slug_maps_to_a_table():
    assert {s.model for s in TABLES} == set(SLUGS.values())


def test_unknown_slug_rejected_with_valid_list():
    with pytest.raises(ValueError) as exc:
        select_tables("fd,crypto")
    assert "crypto" in str(exc.value)
    assert "fd, rd, stock" in str(exc.value)
