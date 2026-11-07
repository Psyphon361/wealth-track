import { describe, expect, it } from "vitest";
import {
  canReinvest,
  canSell,
  canSettle,
  changedTypes,
  destinationOptions,
  effectText,
  exitGain,
  exitTitle,
  exitWhere,
  gainText,
  heldText,
  isSellableType,
  isSettleableType,
  landedInAccount,
  paidFromText,
  parseChoice,
  periodBetween,
  priceFieldText,
  priceHint,
  priceRequestPath,
  quantityWithUnit,
  readPrice,
  reinvestPrefillFor,
  reinvestSummary,
  saleSummary,
  sellDestination,
  sellsAll,
  settleDestination,
  successLine,
  suggestedAccountName,
  undoableExitId,
  type CashAccount,
} from "./exits";

const accounts: CashAccount[] = [
  { id: 7, name: "HDFC Savings", balance: 120000 },
  { id: 9, name: "SBI Salary", balance: 5000.5 },
];

describe("which holdings can be sold or settled", () => {
  it("knows the sellable and settleable types", () => {
    for (const t of ["stock", "bond", "mf", "gold", "other"] as const) {
      expect(isSellableType(t)).toBe(true);
    }
    for (const t of ["fd", "rd", "cash", "pf", "nps"] as const) {
      expect(isSellableType(t)).toBe(false);
    }
    expect(isSettleableType("fd")).toBe(true);
    expect(isSettleableType("rd")).toBe(true);
    expect(isSettleableType("bond")).toBe(true);
    expect(isSettleableType("stock")).toBe(false);
  });

  it("sells only active holdings of a sellable type", () => {
    expect(canSell("stock", { status: "active" })).toBe(true);
    expect(canSell("stock", { status: "sold" })).toBe(false);
    expect(canSell("bond", { status: "matured" })).toBe(false);
    expect(canSell("fd", { status: "active" })).toBe(false);
  });

  it("settles only matured, unsettled, unsold deposits and bonds", () => {
    expect(canSettle("fd", { status: "matured", settled: false })).toBe(true);
    expect(canSettle("bond", { status: "matured" })).toBe(true);
    expect(canSettle("fd", { status: "matured", settled: true })).toBe(false);
    expect(canSettle("bond", { status: "sold", closed_on: "2026-05-01" })).toBe(false);
    expect(canSettle("fd", { status: "active" })).toBe(false);
    expect(canSettle("stock", { status: "matured" })).toBe(false);
  });
});

describe("sale summary", () => {
  it("works out gross, what you get, cost and gain for a full sale", () => {
    const s = saleSummary({
      type: "stock",
      held: 40,
      invested: 100000,
      quantity: 40,
      price: 2800,
      amount: null,
      charges: 250,
    });
    expect(s).toMatchObject({
      gross: 112000,
      charges: 250,
      youGet: 111750,
      cost: 100000,
      gain: 11750,
      full: true,
      estimated: false,
      hasCost: true,
    });
    expect(s?.gainPct).toBeCloseTo(11.75, 6);
  });

  it("takes the proportional cost for a partial sale and flags funds as estimates", () => {
    const stock = saleSummary({
      type: "stock",
      held: 40,
      invested: 100000,
      quantity: 10,
      price: 2000,
      amount: null,
      charges: 0,
    });
    expect(stock).toMatchObject({ cost: 25000, gain: -5000, full: false, estimated: false });
    const fund = saleSummary({
      type: "mf",
      held: 100,
      invested: 50000,
      quantity: 20,
      price: 600,
      amount: null,
      charges: 0,
    });
    expect(fund).toMatchObject({ cost: 10000, gain: 2000, estimated: true });
  });

  it("treats Other as a whole sale of the entered amount", () => {
    const s = saleSummary({
      type: "other",
      held: null,
      invested: 0,
      quantity: null,
      price: null,
      amount: 250000,
      charges: 1000,
    });
    expect(s).toMatchObject({ youGet: 249000, cost: 0, hasCost: false, gainPct: null, full: true });
    expect(gainText(s!)).toBeNull();
  });

  it("returns null for incomplete or impossible input", () => {
    const base = { type: "stock" as const, held: 40, invested: 1000, amount: null, charges: 0 };
    expect(saleSummary({ ...base, quantity: null, price: 10 })).toBeNull();
    expect(saleSummary({ ...base, quantity: 10, price: null })).toBeNull();
    expect(saleSummary({ ...base, quantity: 41, price: 10 })).toBeNull();
    expect(saleSummary({ ...base, quantity: 0, price: 10 })).toBeNull();
  });

  it("words the gain or the loss", () => {
    expect(gainText({ gain: 2500, hasCost: true })).toBe("Gain ₹2,500");
    expect(gainText({ gain: -300.5, hasCost: true })).toBe("Loss ₹300.50");
  });

  it("recognises a sale of everything", () => {
    expect(sellsAll(12.5, 12.5)).toBe(true);
    expect(sellsAll(12.5, 12)).toBe(false);
    expect(sellsAll(null, 1)).toBe(false);
  });
});

describe("held period", () => {
  it("measures whole years, months and days", () => {
    expect(periodBetween("2025-01-15", "2026-04-15")).toEqual({ years: 1, months: 3, days: 0 });
    expect(periodBetween("2025-01-31", "2025-02-28")).toEqual({ years: 0, months: 1, days: 0 });
    expect(periodBetween("2026-10-01", "2026-10-21")).toEqual({ years: 0, months: 0, days: 20 });
    expect(periodBetween("2026-10-21", "2026-10-01")).toEqual({ years: 0, months: 0, days: 0 });
  });

  it("words it", () => {
    expect(heldText("2025-01-15", "2026-04-15")).toBe("held 1 yr 3 mo");
    expect(heldText("2024-01-15", "2026-01-15")).toBe("held 2 yrs");
    expect(heldText("2026-01-15", "2026-06-15")).toBe("held 5 mo");
    expect(heldText("2026-10-01", "2026-10-21")).toBe("held 20 days");
    expect(heldText("2026-10-20", "2026-10-21")).toBe("held 1 day");
    expect(heldText("2026-10-21", "2026-10-21")).toBe("held less than a day");
    expect(heldText(null, "2026-10-21")).toBeNull();
    expect(heldText("2026-10-22", "2026-10-21")).toBeNull();
  });
});

describe("quantity and price wording", () => {
  it("adds the unit", () => {
    expect(quantityWithUnit("stock", 40)).toBe("40 shares");
    expect(quantityWithUnit("stock", 1)).toBe("1 share");
    expect(quantityWithUnit("mf", 12.5)).toBe("12.5 units");
    expect(quantityWithUnit("gold", 5)).toBe("5 g");
    expect(quantityWithUnit("bond", 3)).toBe("3 bonds");
  });

  it("formats prices", () => {
    expect(priceFieldText(123.45)).toBe("123.45");
    expect(priceFieldText(52.12)).toBe("52.12");
    expect(priceFieldText(100)).toBe("100");
    expect(priceHint({ price: 123.45, date: "2026-11-05" })).toBe(
      "Price on 5 Nov 2026: ₹123.45",
    );
  });

  it("builds the price request and reads each response", () => {
    expect(priceRequestPath({ kind: "stock", masterId: 5 }, "2026-11-05")).toBe(
      "/master/stock/5/close?date=2026-11-05",
    );
    expect(priceRequestPath({ kind: "mf", schemeCode: 120716 }, "2026-11-05")).toBe(
      "/master/mf/120716/nav?date=2026-11-05",
    );
    expect(
      priceRequestPath({ kind: "gold", metal: "silver", purity: "999" }, "2026-11-05"),
    ).toBe("/master/gold/rate?metal=silver&purity=999&date=2026-11-05");
    expect(readPrice("stock", { price: 10, price_date: "2026-11-04", source: "history" })).toEqual({
      price: 10,
      date: "2026-11-04",
    });
    expect(readPrice("mf", { nav: 20.5, nav_date: "2026-11-04" })).toEqual({
      price: 20.5,
      date: "2026-11-04",
    });
    expect(readPrice("gold", { rate_per_gram: 7000, rate_date: "2026-11-03" })).toEqual({
      price: 7000,
      date: "2026-11-03",
    });
    expect(readPrice("gold", { nope: 1 })).toBeNull();
  });
});

describe("where the money went", () => {
  it("lists each account, a new one and spent elsewhere for a sale", () => {
    const options = destinationOptions(accounts);
    expect(options.map((o) => o.value)).toEqual(["cash:7", "cash:9", "new", "none"]);
    expect(options[0].label).toBe("HDFC Savings · ₹1,20,000");
    expect(options[1].label).toBe("SBI Salary · ₹5,000.50");
    expect(options[2].label).toBe("A New Savings Account");
    expect(options[3].label).toBe("Spent Or Moved Elsewhere (Not Counted)");
  });

  it("offers no renewals", () => {
    expect(destinationOptions([]).map((o) => o.value)).toEqual(["new", "none"]);
  });

  it("parses the choice values", () => {
    expect(parseChoice("cash:7")).toEqual({ kind: "cash", id: 7 });
    expect(parseChoice("new")).toEqual({ kind: "new" });
    expect(parseChoice("renew_fd")).toBeNull();
    expect(parseChoice("none")).toEqual({ kind: "none" });
    expect(parseChoice("")).toBeNull();
    expect(parseChoice("cash:x")).toBeNull();
  });

  it("says what each choice does to net worth", () => {
    expect(effectText("cash:7", accounts, 105000)).toBe("HDFC Savings: ₹1,20,000 → ₹2,25,000");
    expect(effectText("new", accounts, 105000)).toBe("Adds ₹1,05,000 to your net worth");
    expect(effectText("renew_fd", accounts, 105000)).toBeNull();
    expect(effectText("none", accounts, 105000)).toBe(
      "This ₹1,05,000 won't be added to your net worth.",
    );
    expect(effectText("none", accounts, 105000)).not.toContain("Not Tracking");
  });

  it("says nothing until there is a choice and an amount", () => {
    expect(effectText("", accounts, 100)).toBeNull();
    expect(effectText("new", accounts, null)).toBeNull();
    expect(effectText("new", accounts, 0)).toBeNull();
    expect(effectText("cash:99", accounts, 100)).toBeNull();
  });

  it("names a new account after the bank when known", () => {
    expect(suggestedAccountName("HDFC Bank")).toBe("HDFC Bank Savings");
    expect(suggestedAccountName("  ")).toBe("");
    expect(suggestedAccountName(null)).toBe("");
  });

  it("builds the destination objects", () => {
    expect(sellDestination("cash:7", "")).toEqual({ kind: "cash_existing", cash_id: 7 });
    expect(sellDestination("new", "  My Account ")).toEqual({
      kind: "cash_new",
      cash_name: "My Account",
    });
    expect(sellDestination("none", "")).toEqual({ kind: "none" });
    expect(sellDestination("", "")).toBeNull();
    expect(sellDestination("renew_fd", "")).toBeNull();
    expect(settleDestination("renew_fd", "")).toBeNull();
    expect(settleDestination("cash:7", "")).toEqual({ kind: "cash_existing", cash_id: 7 });
    expect(settleDestination("none", "")).toEqual({ kind: "none" });
  });

  it("lists the types an exit changes", () => {
    expect(changedTypes("stock", { cash_holding_id: null })).toEqual(["stock"]);
    expect(changedTypes("fd", { cash_holding_id: 7 })).toEqual(["fd", "cash"]);
  });
});

describe("the exits list", () => {
  it("titles each exit", () => {
    expect(exitTitle("stock", { kind: "sale", quantity: 40 })).toBe("Sold 40 shares");
    expect(exitTitle("other", { kind: "sale", quantity: null })).toBe("Sold");
    expect(exitTitle("fd", { kind: "maturity", quantity: null })).toBe("Settled");
  });

  it("says where the money went", () => {
    expect(exitWhere({ destination: "cash", cash_holding_id: 7 }, "HDFC Savings")).toEqual({
      text: "Into HDFC Savings",
    });
    expect(exitWhere({ destination: "cash", cash_holding_id: 7 }, null).text).toBe(
      "Into a cash account",
    );
    expect(exitWhere({ destination: "none", cash_holding_id: null }, null).text).toBe(
      "Spent or moved elsewhere",
    );
  });

  it("words the success step", () => {
    expect(successLine({ amount: 107186, cash_added: null }, "HDFC Savings")).toBe(
      "₹1,07,186 is now in HDFC Savings.",
    );
    expect(successLine({ amount: 110000, cash_added: 107186 }, "HDFC Savings")).toBe(
      "₹1,07,186 is now in HDFC Savings.",
    );
    expect(landedInAccount({ cash_holding_id: 7 })).toBe(true);
    expect(landedInAccount({ cash_holding_id: null })).toBe(false);
  });

  it("summarises reinvestment of an exit's money", () => {
    const base = { cash_holding_id: 7, amount: 107186, cash_added: 107186 };
    expect(
      reinvestSummary({ ...base, reinvested: 50000, left_in_account: 57186 }, "HDFC Savings"),
    ).toBe("₹50,000 reinvested · ₹57,186 still in HDFC Savings");
    expect(
      reinvestSummary({ ...base, reinvested: 0, left_in_account: 107186 }, "HDFC Savings"),
    ).toBe("₹1,07,186 in HDFC Savings");
    expect(
      reinvestSummary({ ...base, cash_holding_id: null, reinvested: 0, left_in_account: null }, null),
    ).toBeNull();
  });

  it("offers Reinvest only while money is left in the account", () => {
    const base = { cash_holding_id: 7, amount: 100, cash_added: 100 };
    expect(canReinvest({ ...base, left_in_account: 40 })).toBe(true);
    expect(canReinvest({ ...base, left_in_account: 0 })).toBe(false);
    expect(canReinvest({ ...base, cash_holding_id: null, left_in_account: null })).toBe(false);
  });

  it("builds the reinvest prefill from what is left", () => {
    const exit = {
      id: 5,
      date: "2026-11-01",
      amount: 110000,
      cash_holding_id: 7,
      cash_added: 107186,
      left_in_account: 57186,
    };
    expect(reinvestPrefillFor("mf", exit, "HDFC Savings")).toEqual({
      type: "mf",
      amount: 57186,
      date: "2026-11-01",
      cash_id: 7,
      cash_name: "HDFC Savings",
      from_exit_id: 5,
    });
    expect(reinvestPrefillFor("mf", { ...exit, left_in_account: null }, "X")?.amount).toBe(107186);
    expect(reinvestPrefillFor("mf", { ...exit, cash_holding_id: null }, "X")).toBeNull();
  });

  it("words the paid-from line", () => {
    expect(
      paidFromText({
        paid_from: { cash_holding_id: 7, cash_name: "HDFC Savings", amount: 50000, date: "2026-11-02" },
      }),
    ).toBe("Paid from HDFC Savings · ₹50,000");
    expect(paidFromText({ paid_from: null })).toBeNull();
    expect(paidFromText({})).toBeNull();
  });

  it("shows the realised gain or loss", () => {
    expect(exitGain({ amount: 111750, cost: 100000 })).toEqual({ text: "Gain ₹11,750", value: 11750 });
    expect(exitGain({ amount: 90000, cost: 100000 })).toEqual({ text: "Loss ₹10,000", value: -10000 });
    expect(exitGain({ amount: 5, cost: 0 })).toBeNull();
    expect(exitGain({ amount: 100, cost: 100 })).toBeNull();
  });

  it("allows undoing only the newest exit", () => {
    expect(undoableExitId([{ id: 9 }, { id: 4 }])).toBe(9);
    expect(undoableExitId([])).toBeNull();
  });
});
