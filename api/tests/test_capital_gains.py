from datetime import date
from decimal import Decimal

from app.services import capital_gains as cg
from app.services.capital_gains import MfTxn, SaleInput

D = Decimal


def sale(**kw):
    base = dict(
        exit_id=1,
        asset_type="stock",
        holding_id=1,
        name="Acme",
        sold_on=date(2025, 1, 10),
        quantity=D(10),
        proceeds=D(1000),
        cost=D(800),
        bought_on=date(2024, 1, 1),
        stock_kind="stock",
    )
    base.update(kw)
    return SaleInput(**base)


def test_available_fys():
    out = cg.available_fys(date(2026, 11, 8), [date(2024, 5, 1), date(2024, 6, 1)])
    assert [i["start_year"] for i in out] == [2026, 2024]
    assert out[0] == {"start_year": 2026, "label": "2026-27", "is_current": True}
    assert out[1]["is_current"] is False


def test_add_months_clamps():
    assert cg.add_months(date(2023, 1, 31), 1) == date(2023, 2, 28)
    assert cg.add_months(date(2024, 2, 29), 12) == date(2025, 2, 28)
    assert cg.add_months(date(2023, 11, 15), 3) == date(2024, 2, 15)


# --- classification ----------------------------------------------------------------------------


def test_stock_classes():
    assert cg.classify(sale(stock_kind="stock")) == ("equity", [])
    assert cg.classify(sale(stock_kind="etf", name="Nippon Nifty BeES")) == ("equity", ["guessed_class"])
    assert cg.classify(sale(stock_kind="etf", name="SBI Gold ETF")) == ("listed_other", ["guessed_class"])
    assert cg.classify(sale(stock_kind=None, name="Silver BeES")) == ("listed_other", ["guessed_class"])
    assert cg.classify(sale(stock_kind="etf", name="Gilt Bond ETF"))[0] == "debt_fund"
    assert cg.classify(sale(stock_kind="etf", name="Bharat IBX Fund"))[0] == "debt_fund"


def mf(category, amfi=None, name="Some Fund"):
    return sale(asset_type="mf", mf_category=category, amfi_category=amfi, name=name, stock_kind=None)


def test_mf_classes():
    assert cg.classify(mf("equity")) == ("equity", [])
    assert cg.classify(mf("elss")) == ("equity", [])
    assert cg.classify(mf("debt")) == ("debt_fund", [])
    assert cg.classify(mf("liquid")) == ("debt_fund", [])
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Arbitrage Fund")) == ("equity", [])
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Balanced Advantage"))[0] == "equity"
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Equity Savings"))[0] == "equity"
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Conservative Hybrid Fund")) == ("debt_fund", [])
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Multi Asset Allocation")) == ("other", ["multi_asset"])
    assert cg.classify(mf("hybrid", "Hybrid Scheme - Something"))== ("equity", ["guessed_class"])
    assert cg.classify(mf("index", name="UTI Nifty 50 Index")) == ("equity", ["guessed_class"])
    assert cg.classify(mf("other", name="HDFC Gold Fund")) == ("other", ["guessed_class"])
    assert cg.classify(mf("other", name="Corporate Bond Fof"))[0] == "debt_fund"


def test_bond_gold_other_classes():
    assert cg.classify(sale(asset_type="bond", bond_type="sgb")) == ("bond", [])
    assert cg.classify(sale(asset_type="bond", bond_has_master=False)) == ("bond", ["guessed_class"])
    assert cg.classify(sale(asset_type="gold")) == ("other", [])
    assert cg.classify(sale(asset_type="other", other_category="Crypto")) == ("crypto", [])
    assert cg.classify(sale(asset_type="other", other_category="Property")) == ("other", [])


# --- terms -------------------------------------------------------------------------------------


def test_equity_twelve_month_boundary():
    b = date(2024, 1, 1)
    assert cg.lot_bucket("equity", b, date(2025, 1, 1))[:2] == ("equity_st", "short")
    assert cg.lot_bucket("equity", b, date(2025, 1, 2))[:2] == ("equity_lt", "long")


def test_month_end_clamp_boundary():
    b = date(2023, 2, 28)
    assert cg.lot_bucket("equity", b, date(2024, 2, 28))[1] == "short"
    assert cg.lot_bucket("equity", b, date(2024, 2, 29))[1] == "long"
    b = date(2024, 2, 29)
    assert cg.lot_bucket("equity", b, date(2025, 2, 28))[1] == "short"
    assert cg.lot_bucket("equity", b, date(2025, 3, 1))[1] == "long"


def test_cutoff_both_sides():
    b = date(2022, 1, 1)
    assert cg.lot_bucket("equity", b, date(2024, 7, 22))[0] == "equity_lt_old"
    assert cg.lot_bucket("equity", b, date(2024, 7, 23))[0] == "equity_lt"
    b = date(2024, 7, 1)
    assert cg.lot_bucket("equity", b, date(2024, 7, 22))[0] == "equity_st_old"
    assert cg.lot_bucket("equity", b, date(2024, 7, 23))[0] == "equity_st"


def test_grandfathering_flag():
    assert cg.lot_bucket("equity", date(2018, 1, 31), date(2025, 1, 1)) == (
        "equity_lt",
        "long",
        ["grandfathering"],
    )
    assert cg.lot_bucket("equity", date(2018, 2, 1), date(2025, 1, 1))[2] == []
    built = cg.build_sale(sale(bought_on=date(2017, 5, 1), sold_on=date(2025, 1, 1)))
    assert "grandfathering" in built["flags"]


def test_debt_fund_rules():
    # bought on/after 1 Apr 2023: always slab
    assert cg.lot_bucket("debt_fund", date(2023, 4, 1), date(2030, 1, 1)) == ("slab", "short", [])
    # bought before: 24 months after the cut-off
    b = date(2023, 3, 31)
    assert cg.lot_bucket("debt_fund", b, date(2025, 3, 31))[:2] == ("slab", "short")
    assert cg.lot_bucket("debt_fund", b, date(2025, 4, 1))[:2] == ("other_lt", "long")
    # sold before the cut-off: 36 months, long has no bucket
    b = date(2020, 1, 1)
    assert cg.lot_bucket("debt_fund", b, date(2023, 1, 1))[:2] == ("slab", "short")
    assert cg.lot_bucket("debt_fund", b, date(2023, 1, 2)) == (None, "long", ["old_rules"])


def test_bond_listed_other_other_rules():
    b = date(2023, 6, 1)
    assert cg.lot_bucket("bond", b, date(2024, 6, 1))[:2] == ("slab", "short")
    assert cg.lot_bucket("bond", b, date(2024, 7, 23))[:2] == ("other_lt", "long")
    assert cg.lot_bucket("listed_other", date(2022, 1, 1), date(2024, 1, 1)) == (None, "long", ["old_rules"])
    assert cg.lot_bucket("other", date(2022, 7, 23), date(2024, 7, 23))[:2] == ("slab", "short")
    assert cg.lot_bucket("other", date(2022, 7, 23), date(2024, 7, 24))[:2] == ("other_lt", "long")
    assert cg.lot_bucket("other", date(2020, 1, 1), date(2024, 7, 22)) == (None, "long", ["old_rules"])


def test_crypto_and_no_purchase_date():
    assert cg.lot_bucket("crypto", date(2020, 1, 1), date(2025, 1, 1)) == ("crypto", "flat", [])
    assert cg.lot_bucket("crypto", None, date(2025, 1, 1))[0] == "crypto"
    assert cg.lot_bucket("other", None, date(2025, 1, 1)) == (None, None, ["no_purchase_date"])
    built = cg.build_sale(sale(asset_type="other", other_category="Art", bought_on=None, quantity=None))
    assert built["flags"] == ["no_purchase_date"]
    assert built["lots"][0]["days_held"] is None


# --- lots --------------------------------------------------------------------------------------


def mf_sale(cost, proceeds, redemption_id=9, txns=None):
    txns = txns if txns is not None else [
        MfTxn(1, date(2023, 1, 10), "purchase", D(10), D(1000)),
        MfTxn(2, date(2024, 6, 10), "purchase", D(10), D(2000)),
        MfTxn(9, date(2025, 1, 10), "redemption", D(15), D(4500)),
    ]
    return SaleInput(
        exit_id=5,
        asset_type="mf",
        holding_id=3,
        name="Eq Fund",
        sold_on=date(2025, 1, 10),
        quantity=D(15),
        proceeds=D(proceeds),
        cost=D(cost),
        bought_on=date(2023, 1, 10),
        mf_category="equity",
        mf_txns=txns,
        mf_transaction_id=redemption_id,
    )


def test_mf_partial_fifo_spans_short_and_long():
    built = cg.build_sale(mf_sale(cost="2000", proceeds="4500"))
    lots = built["lots"]
    assert len(lots) == 2
    assert lots[0]["bought_on"] == date(2023, 1, 10) and lots[0]["quantity"] == D(10)
    assert lots[0]["cost"] == D("1000.00") and lots[0]["proceeds"] == D("3000.00")
    assert lots[0]["term"] == "long" and lots[0]["bucket"] == "equity_lt"
    assert lots[1]["quantity"] == D(5) and lots[1]["cost"] == D("1000.00")
    assert lots[1]["proceeds"] == D("1500.00")
    assert lots[1]["term"] == "short" and lots[1]["bucket"] == "equity_st"
    assert sum(l["proceeds"] for l in lots) == D("4500.00")
    assert lots[0]["days_held"] == (date(2025, 1, 10) - date(2023, 1, 10)).days


def test_mf_earlier_redemption_consumes_first():
    txns = [
        MfTxn(1, date(2023, 1, 10), "purchase", D(10), D(1000)),
        MfTxn(2, date(2023, 2, 10), "redemption", D(4), D(500)),
        MfTxn(3, date(2024, 6, 10), "purchase", D(10), D(2000)),
        MfTxn(9, date(2025, 1, 10), "redemption", D(8), D(1600)),
    ]
    built = cg.build_sale(mf_sale(cost="1000.00", proceeds="1600", txns=txns))
    lots = built["lots"]
    assert [l["quantity"] for l in lots] == [D(6), D(2)]
    assert lots[0]["cost"] == D("600.00")
    assert lots[1]["cost"] == D("400.00")


def test_mf_rounding_remainder_on_last_lot():
    txns = [
        MfTxn(1, date(2023, 1, 1), "purchase", D(1), D(100)),
        MfTxn(2, date(2023, 1, 2), "purchase", D(1), D(100)),
        MfTxn(3, date(2023, 1, 3), "purchase", D(1), D(100)),
        MfTxn(9, date(2023, 6, 1), "redemption", D(3), D(400)),
    ]
    s = mf_sale(cost="300", proceeds="100.00", txns=txns)
    lots = cg.split_lots(s)
    assert [l["proceeds"] for l in lots] == [D("33.33"), D("33.33"), D("33.34")]


def test_mf_lot_gains_sum_to_sale_gain():
    txns = [
        MfTxn(1, date(2023, 1, 1), "purchase", D(1), D("100.01")),
        MfTxn(2, date(2023, 1, 2), "purchase", D(1), D("100.01")),
        MfTxn(3, date(2023, 1, 3), "purchase", D(1), D("100.01")),
        MfTxn(9, date(2023, 6, 1), "redemption", D(3), D(400)),
    ]
    s = mf_sale(cost="300.20", proceeds="411.11", txns=txns)
    lots = cg.split_lots(s)
    assert len(lots) == 3
    assert sum(l["cost"] for l in lots) == D("300.20")
    assert sum(l["proceeds"] - l["cost"] for l in lots) == D("411.11") - D("300.20")


def test_mf_fifo_mismatch_falls_back():
    s = mf_sale(cost="2500", proceeds="4500")  # FIFO says 2000
    lots = cg.build_sale(s)["lots"]
    assert len(lots) == 1
    assert lots[0]["bought_on"] == date(2023, 1, 10)
    assert lots[0]["cost"] == D("2500.00") and lots[0]["gain"] == D("2000.00")
    # within 1.00 tolerance keeps FIFO
    assert len(cg.build_sale(mf_sale(cost="2000.80", proceeds="4500"))["lots"]) == 2


def test_mf_missing_redemption_falls_back():
    assert len(cg.build_sale(mf_sale(cost="2000", proceeds="4500", redemption_id=77))["lots"]) == 1
    assert len(cg.build_sale(mf_sale(cost="2000", proceeds="4500", txns=[]))["lots"]) == 1


# --- totals ------------------------------------------------------------------------------------


def lot_sale(exit_id, cls_kind, gain, bought, sold, **kw):
    """A built sale with one lot of given gain (cost 1000)."""
    return cg.build_sale(
        sale(
            exit_id=exit_id,
            proceeds=D(1000) + D(gain),
            cost=D(1000),
            bought_on=bought,
            sold_on=sold,
            **cls_kind,
            **kw,
        )
    )


EQ = {"stock_kind": "stock"}
OTHER = {"asset_type": "other", "other_category": "Art", "stock_kind": None}
CRYPTO = {"asset_type": "other", "other_category": "Crypto", "stock_kind": None}
SOLD = date(2025, 1, 10)


def bucket(totals, key):
    return next(b for b in totals["buckets"] if b["key"] == key)


def test_basic_tax_and_order():
    sales = [
        lot_sale(1, EQ, 10000, date(2024, 9, 1), SOLD),  # equity_st
        lot_sale(2, EQ, 200000, date(2023, 1, 1), SOLD),  # equity_lt
        lot_sale(3, OTHER, 5000, date(2024, 9, 1), SOLD),  # slab
    ]
    t = cg.fy_totals(sales, 2024)
    assert [b["key"] for b in t["buckets"]] == ["equity_st", "equity_lt", "slab"]
    st = bucket(t, "equity_st")
    assert st["tax"] == D("2000.00") and st["rate"] == D(20) and st["label"] == "Equity, Short Term"
    lt = bucket(t, "equity_lt")
    assert lt["exemption"] == D(125000) and lt["taxable"] == D(75000)
    assert lt["tax"] == D("9375.00")
    sl = bucket(t, "slab")
    assert sl["rate"] is None and sl["tax"] is None and sl["taxable"] == D(5000)
    s = t["summary"]
    assert s["fixed_rate_tax"] == D("11375.00") and s["slab_gains"] == D(5000)
    assert s["short_term_net"] == D(15000) and s["long_term_net"] == D(200000)
    assert s["exemption_used"] == D(125000) and s["sales_count"] == 3


def test_exemption_old_fy_and_spread():
    old = date(2024, 3, 1)
    sales = [
        lot_sale(1, EQ, 60000, date(2022, 1, 1), SOLD),  # equity_lt
        lot_sale(2, EQ, 100000, date(2020, 1, 1), date(2024, 7, 1)),  # equity_lt_old
    ]
    t = cg.fy_totals(sales, 2024)
    assert bucket(t, "equity_lt")["exemption"] == D(60000)
    assert bucket(t, "equity_lt")["taxable"] == D(0)
    assert bucket(t, "equity_lt_old")["exemption"] == D(65000)
    assert bucket(t, "equity_lt_old")["taxable"] == D(35000)
    assert bucket(t, "equity_lt_old")["tax"] == D("3500.00")
    assert t["summary"]["exemption_used"] == D(125000)
    # FY 2023-24 uses 1,00,000
    assert cg.exemption_limit(2023) == D(100000)
    sales = [lot_sale(1, EQ, 150000, date(2020, 1, 1), old)]
    t = cg.fy_totals(sales, 2023)
    assert bucket(t, "equity_lt_old")["exemption"] == D(100000)
    assert bucket(t, "equity_lt_old")["taxable"] == D(50000)


def test_short_loss_offsets_long_gain_in_order():
    sales = [
        lot_sale(1, EQ, -30000, date(2024, 9, 1), SOLD),  # equity_st loss
        lot_sale(2, OTHER, 10000, date(2024, 9, 1), SOLD),  # slab gain
        lot_sale(3, OTHER, 100000, date(2022, 1, 1), SOLD),  # other_lt gain
        lot_sale(4, EQ, 50000, date(2022, 1, 1), SOLD),  # equity_lt gain
    ]
    t = cg.fy_totals(sales, 2024)
    assert bucket(t, "slab")["set_off"] == D(10000)
    assert bucket(t, "other_lt")["set_off"] == D(20000)
    assert bucket(t, "equity_lt")["set_off"] == D(0)
    assert bucket(t, "other_lt")["taxable"] == D(80000)
    s = t["summary"]
    assert s["losses_set_off"] == D(30000) and s["unused_losses"] == D(0)
    assert bucket(t, "equity_st")["taxable"] == D(0)


def test_long_loss_not_against_short():
    sales = [
        lot_sale(1, OTHER, -40000, date(2022, 1, 1), SOLD),  # other_lt loss
        lot_sale(2, EQ, 10000, date(2024, 9, 1), SOLD),  # equity_st gain
        lot_sale(3, EQ, 150000, date(2022, 1, 1), SOLD),  # equity_lt gain
    ]
    t = cg.fy_totals(sales, 2024)
    assert bucket(t, "equity_st")["set_off"] == D(0)
    assert bucket(t, "equity_st")["taxable"] == D(10000)
    assert bucket(t, "equity_lt")["set_off"] == D(40000)
    # exemption applies after set-off: 150000 - 40000 = 110000 < 125000
    assert bucket(t, "equity_lt")["exemption"] == D(110000)
    assert bucket(t, "equity_lt")["taxable"] == D(0)


def test_long_loss_unused_when_only_short_gains():
    sales = [
        lot_sale(1, EQ, -40000, date(2022, 1, 1), SOLD),  # equity_lt loss
        lot_sale(2, EQ, 10000, date(2024, 9, 1), SOLD),
    ]
    t = cg.fy_totals(sales, 2024)
    assert t["summary"]["losses_set_off"] == D(0)
    assert t["summary"]["unused_losses"] == D(40000)
    assert bucket(t, "equity_st")["taxable"] == D(10000)


def test_crypto_loss_ignored_and_no_setoff():
    sales = [
        lot_sale(1, CRYPTO, 10000, date(2024, 1, 1), SOLD),
        lot_sale(2, CRYPTO, -4000, date(2024, 1, 1), SOLD),
        lot_sale(3, EQ, 20000, date(2024, 9, 1), SOLD),
    ]
    t = cg.fy_totals(sales, 2024)
    c = bucket(t, "crypto")
    assert c["term"] == "flat" and c["rate"] == D(30)
    assert c["gains"] == D(10000) and c["losses"] == D(4000) and c["net"] == D(6000)
    assert c["taxable"] == D(10000) and c["tax"] == D("3000.00")
    assert bucket(t, "equity_st")["set_off"] == D(0)
    assert t["summary"]["unused_losses"] == D(0)
    # crypto loss alone gives no set-off against equity
    t = cg.fy_totals([lot_sale(1, CRYPTO, -4000, date(2024, 1, 1), SOLD), sales[2]], 2024)
    assert bucket(t, "equity_st")["taxable"] == D(20000)
    assert t["summary"]["unused_losses"] == D(0)


def test_excluded_lots_reported_not_taxed():
    sales = [
        lot_sale(1, OTHER, 5000, None, SOLD),  # no purchase date
        lot_sale(2, OTHER, 5000, date(2020, 1, 1), date(2024, 7, 1)),  # old rules long
    ]
    assert sales[0]["flags"] == ["no_purchase_date"]
    assert sales[1]["flags"] == ["old_rules"]
    t = cg.fy_totals(sales, 2024)
    assert t["buckets"] == []
    assert t["summary"]["excluded_lots"] == 2 and t["summary"]["sales_count"] == 2
    assert sales[1]["lots"][0]["term"] == "long" and sales[1]["lots"][0]["bucket"] is None


def test_capital_gains_filters_by_fy():
    inputs = [
        sale(exit_id=1, sold_on=date(2025, 3, 31)),
        sale(exit_id=2, sold_on=date(2025, 4, 1)),
        sale(exit_id=3, sold_on=date(2024, 3, 31)),
    ]
    out = cg.capital_gains(inputs, 2024)
    assert [s["exit_id"] for s in out["sales"]] == [1]
    out = cg.capital_gains(inputs, 2025)
    assert [s["exit_id"] for s in out["sales"]] == [2]
    assert out["summary"]["sales_count"] == 1
