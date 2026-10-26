from app.services.market_files import debt_isins, is_html
from tests.market_helpers import read, zip_text


def test_html_shell_is_detected_as_missing_file():
    assert is_html(b"<!DOCTYPE html><html>")
    assert is_html(b"  \n<HTML><HEAD>")
    assert not is_html(b"TradDt,BizDt,Sgmt")
    assert not is_html(zip_text("a,b\n1,2\n"))


def test_debt_isins_reads_headerless_column_and_skips_bad_rows():
    isins = debt_isins(read("nse_debt_sample.csv"))
    assert len(isins) == 8
    assert "INE674K07150" in isins
