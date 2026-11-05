import { describe, expect, it } from "vitest";
import {
  allClassesProjected,
  bondsNote,
  classBarPercent,
  classCountText,
  classPayers,
  classProgressText,
  classTdsPill,
  couponsLeft,
  couponsLeftText,
  fyDisplay,
  fyOptionLabel,
  leftToPay,
  leftToPayLabel,
  parseSlab,
  savingsSentence,
  slabOptionLabel,
  slabTriggerLabel,
  taxCardLabel,
  taxOnInterest,
  tdsLimitMarker,
  tdsSuffix,
} from "./tax";
import type { TaxClassRow, TaxHolding, TaxPayer } from "./types";

const payer = (over: Partial<TaxPayer> = {}): TaxPayer => ({
  key: "issuer:1",
  name: "SBI",
  kind: "bank",
  tds_rule: "threshold",
  threshold: 50000,
  interest_to_date: 20000,
  interest_projected: 60000,
  crosses: true,
  tds_estimate: 6000,
  holdings: [],
  ...over,
});

const holding = (over: Partial<TaxHolding> = {}): TaxHolding => ({
  id: 1,
  type: "bond",
  name: "Ugro 2027",
  interest_to_date: 2000,
  interest_projected: 4750,
  tds_estimate: 475,
  ...over,
});

const classRow = (over: Partial<TaxClassRow> = {}): TaxClassRow => ({
  type: "bond",
  label: "Bonds",
  interest_to_date: 2000,
  interest_projected: 4750,
  tds_estimate: 475,
  holdings_count: 2,
  ...over,
});

describe("fy labels", () => {
  it("uses an en dash", () => {
    expect(fyDisplay("2026-27")).toBe("2026–27");
  });
  it("builds option labels", () => {
    expect(fyOptionLabel({ start_year: 2026, label: "2026-27", is_current: true })).toBe(
      "FY 2026–27",
    );
    expect(fyOptionLabel({ start_year: 2025, label: "2025-26", is_current: false })).toBe(
      "FY 2025–26",
    );
  });
  it("builds slab labels", () => {
    expect(slabOptionLabel(0)).toBe("0% (no tax)");
    expect(slabOptionLabel(5)).toBe("5%");
    expect(slabTriggerLabel(25)).toBe("25% slab");
  });
});

describe("slab maths", () => {
  it("adds 4% cess and rounds to whole rupees", () => {
    expect(taxOnInterest(100000, 30)).toBe(31200);
    expect(taxOnInterest(12345, 10)).toBe(1284);
    expect(taxOnInterest(100000, 0)).toBe(0);
    expect(taxOnInterest(0, 30)).toBe(0);
  });
  it("parses only valid stored slabs", () => {
    expect(parseSlab("30")).toBe(30);
    expect(parseSlab("0")).toBe(0);
    expect(parseSlab("12")).toBeNull();
    expect(parseSlab("")).toBeNull();
    expect(parseSlab("abc")).toBeNull();
    expect(parseSlab(null)).toBeNull();
  });
  it("computes what is left to pay, negative for a refund", () => {
    expect(leftToPay(100000, 10000, 30)).toBe(21200);
    expect(leftToPay(100000, 10000, 5)).toBe(-4800);
    expect(leftToPay(100000, 6000, 0)).toBe(-6000);
    expect(leftToPay(100000, 0, 10)).toBe(10400);
  });
  it("labels a refund as Refund due and everything else as Left to pay", () => {
    expect(leftToPayLabel(-4800)).toBe("Refund due");
    expect(leftToPayLabel(21200)).toBe("Left to pay");
    expect(leftToPayLabel(0)).toBe("Left to pay");
    expect(leftToPayLabel(null)).toBe("Left to pay");
  });
});

describe("footnotes", () => {
  it("pluralises bonds", () => {
    expect(bondsNote(1)).toBe("1 bond without coupon details isn't included.");
    expect(bondsNote(2)).toBe("2 bonds without coupon details aren't included.");
  });
  it("pluralises accounts", () => {
    expect(savingsSentence({ interest_estimate: 1200, accounts: 1 })).toContain("across 1 account.");
    expect(savingsSentence({ interest_estimate: 1200, accounts: 2 })).toContain("across 2 accounts.");
  });
  it("gives the savings footnote in full", () => {
    expect(savingsSentence({ interest_estimate: 1200, accounts: 1 })).toBe(
      "Savings interest is about ₹1,200 across 1 account. It's taxable, with no TDS. Under the old regime up to ₹10,000 of it is deductible (80TTA); the new regime has no such deduction.",
    );
  });
});

describe("taxCardLabel", () => {
  it("reads 'this year' for the current year and names a past year", () => {
    expect(taxCardLabel({ is_current: true, fy: "2026-27" })).toBe("Interest this year, by type");
    expect(taxCardLabel({ is_current: false, fy: "2025-26" })).toBe(
      "Interest in FY 2025–26, by type",
    );
  });
});

describe("classCountText", () => {
  it("pluralises deposits and bonds", () => {
    expect(classCountText(classRow({ type: "fd", holdings_count: 3 }))).toBe(" · 3 deposits");
    expect(classCountText(classRow({ type: "rd", holdings_count: 1 }))).toBe(" · 1 deposit");
    expect(classCountText(classRow({ type: "bond", holdings_count: 6 }))).toBe(" · 6 bonds");
    expect(classCountText(classRow({ type: "bond", holdings_count: 1 }))).toBe(" · 1 bond");
  });
  it("calls savings an estimate", () => {
    expect(classCountText(classRow({ type: "savings", holdings_count: 2 }))).toBe(" · estimate");
  });
});

describe("class bar", () => {
  it("fills with the part already received in the current year", () => {
    const row = classRow({ interest_to_date: 1000, interest_projected: 4000 });
    expect(classBarPercent(row, true, 10000)).toBe(25);
  });
  it("clamps to 0-100 and handles zero", () => {
    expect(classBarPercent(classRow({ interest_to_date: 5000, interest_projected: 4000 }), true, 0)).toBe(100);
    expect(classBarPercent(classRow({ interest_to_date: -5, interest_projected: 4000 }), true, 0)).toBe(0);
    expect(classBarPercent(classRow({ interest_to_date: 0, interest_projected: 0 }), true, 0)).toBe(0);
    expect(classBarPercent(classRow({ interest_projected: 100 }), false, 0)).toBe(0);
  });
  it("shows the share of the year's interest in a past year", () => {
    const rows = [
      classRow({ type: "fd", interest_projected: 4200 }),
      classRow({ type: "bond", interest_projected: 5800 }),
    ];
    const all = allClassesProjected(rows);
    expect(all).toBe(10000);
    expect(classBarPercent(rows[0], false, all)).toBe(42);
    expect(classProgressText(rows[0], false, all)).toBe("42% of the year's interest");
  });
});

describe("classProgressText", () => {
  it("splits received from to come in the current year", () => {
    const row = classRow({ type: "fd", interest_to_date: 6783, interest_projected: 11931 });
    expect(classProgressText(row, true, 0)).toBe("₹6,783 received · ₹5,148 to come");
  });
  it("says so far for savings and never shows a negative to come", () => {
    const sav = classRow({ type: "savings", interest_to_date: 500, interest_projected: 1200 });
    expect(classProgressText(sav, true, 0)).toBe("₹500 so far · ₹700 to come");
    const over = classRow({ type: "fd", interest_to_date: 900, interest_projected: 800 });
    expect(classProgressText(over, true, 0)).toBe("₹900 received · ₹0 to come");
  });
});

describe("classTdsPill", () => {
  const bank = (key: string, crosses: boolean, threshold: number | null = 50000) =>
    classPayers(
      [
        payer({
          key,
          name: key,
          kind: "bank",
          crosses,
          threshold,
          holdings: [holding({ id: 1, type: "fd" })],
        }),
      ],
      "fd",
    )[0];
  const company = (key: string, crosses: boolean) =>
    classPayers(
      [
        payer({
          key,
          name: key,
          kind: "company",
          crosses,
          threshold: 10000,
          holdings: [holding({ id: 2, type: "fd" })],
        }),
      ],
      "fd",
    )[0];

  it("explains savings", () => {
    expect(classTdsPill(classRow({ type: "savings", tds_estimate: 0 }), [])).toEqual({
      text: "Banks don't cut TDS on savings",
      warn: false,
    });
  });
  it("names how many banks are over the limit", () => {
    const row = classRow({ type: "fd", tds_estimate: 6000 });
    expect(classTdsPill(row, [bank("a", true), bank("b", false)])).toEqual({
      text: "₹6,000 TDS · over the limit at 1 bank",
      warn: true,
    });
    expect(classTdsPill(row, [bank("a", true), bank("b", true)]).text).toBe(
      "₹6,000 TDS · over the limit at 2 banks",
    );
  });
  it("says payer when a non-bank is over the limit", () => {
    const row = classRow({ type: "fd", tds_estimate: 900 });
    expect(classTdsPill(row, [bank("a", false), company("c", true)]).text).toBe(
      "₹900 TDS · over the limit at 1 payer",
    );
    expect(classTdsPill(row, [company("c", true), bank("a", true)]).text).toBe(
      "₹900 TDS · over the limit at 2 payers",
    );
  });
  it("falls back to the amount when no payer is flagged", () => {
    expect(classTdsPill(classRow({ type: "rd", tds_estimate: 300 }), [bank("a", false)]).text).toBe(
      "₹300 TDS",
    );
  });
  it("says no TDS under the bank limit, or under each payer's limit", () => {
    const row = classRow({ type: "fd", tds_estimate: 0 });
    expect(classTdsPill(row, [bank("a", false)])).toEqual({
      text: "No TDS · under ₹50,000 per bank",
      warn: false,
    });
    expect(classTdsPill(row, [bank("a", false), company("c", false)]).text).toBe(
      "No TDS · each payer under its limit",
    );
    expect(classTdsPill(row, []).text).toBe("No TDS · each payer under its limit");
  });
  it("explains bond TDS per coupon", () => {
    expect(classTdsPill(classRow({ type: "bond", tds_estimate: 475 }), []).text).toBe(
      "₹475 TDS · 10% of each coupon",
    );
    expect(classTdsPill(classRow({ type: "bond", tds_estimate: 0 }), [])).toEqual({
      text: "No TDS on these bonds",
      warn: false,
    });
  });
});

describe("coupons left and TDS suffix", () => {
  it("counts only unpaid coupons across holdings", () => {
    const pay = (date: string, paid: boolean) => ({ date, gross: 100, tds: 10, net: 90, paid });
    const [p] = classPayers(
      [
        payer({
          kind: "bond",
          holdings: [
            holding({ id: 1, payments: [pay("2026-05-01", true), pay("2026-11-01", false)] }),
            holding({ id: 2, payments: [pay("2027-02-01", false)] }),
            holding({ id: 3 }),
          ],
        }),
      ],
      "bond",
    );
    expect(couponsLeft(p)).toBe(2);
    expect(couponsLeftText(1)).toBe("1 coupon left");
    expect(couponsLeftText(2)).toBe("2 coupons left");
  });
  it("shows TDS or no TDS", () => {
    expect(tdsSuffix(475)).toBe(" · ₹475 TDS");
    expect(tdsSuffix(0)).toBe(" · no TDS");
    expect(tdsSuffix(47.5, true)).toBe(" · ₹47.50 TDS");
  });
});

describe("tdsLimitMarker", () => {
  it("flags a payer over its limit", () => {
    expect(tdsLimitMarker(payer())).toEqual({ text: "Over TDS limit", over: true });
  });
  it("shows the room left within 20% of the limit", () => {
    expect(tdsLimitMarker(payer({ crosses: false, interest_projected: 42000 }))).toEqual({
      text: "₹8,000 to TDS limit",
      over: false,
    });
  });
  it("is null well below the limit", () => {
    expect(tdsLimitMarker(payer({ crosses: false, interest_projected: 30000 }))).toBeNull();
  });
  it("is null for payers without a threshold", () => {
    expect(tdsLimitMarker(payer({ tds_rule: "every_payment", threshold: null, crosses: false }))).toBeNull();
    expect(tdsLimitMarker(payer({ tds_rule: "none", threshold: null, crosses: false }))).toBeNull();
  });
});

describe("classPayers", () => {
  const payers = [
    payer({
      key: "a",
      name: "SBI",
      holdings: [
        holding({ id: 1, type: "fd", name: "FD 1", interest_to_date: 100, interest_projected: 300, tds_estimate: 30 }),
        holding({ id: 2, type: "rd", name: "RD 1", interest_to_date: 50, interest_projected: 80, tds_estimate: 8 }),
      ],
    }),
    payer({
      key: "b",
      name: "Bajaj",
      kind: "company",
      holdings: [holding({ id: 3, type: "fd", name: "FD 2", interest_projected: 900, tds_estimate: 90 })],
    }),
    payer({ key: "c", name: "Ugro", kind: "bond", holdings: [holding({ id: 4 })] }),
  ];
  it("keeps only the class's holdings and sums them, biggest payer first", () => {
    const fd = classPayers(payers, "fd");
    expect(fd.map((p) => p.name)).toEqual(["Bajaj", "SBI"]);
    expect(fd[1]).toMatchObject({ interest_to_date: 100, interest_projected: 300, tds_estimate: 30 });
    expect(classPayers(payers, "rd").map((p) => p.name)).toEqual(["SBI"]);
  });
  it("uses bond payers for bonds and none for savings", () => {
    expect(classPayers(payers, "bond").map((p) => p.name)).toEqual(["Ugro"]);
    expect(classPayers(payers, "savings")).toEqual([]);
  });
});
