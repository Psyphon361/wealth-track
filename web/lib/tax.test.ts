import { describe, expect, it } from "vitest";
import {
  barShare,
  bondsNote,
  fyDisplay,
  parseSlab,
  slabSentence,
  taxableShare,
  taxOnInterest,
  fyOptionLabel,
  interestSubline,
  joinNames,
  payerHint,
  savingsSentence,
  tdsSentence,
} from "./tax";
import type { AnalyticsTax, TaxPayer } from "./types";

const payer = (over: Partial<TaxPayer> = {}): TaxPayer => ({
  key: "issuer:1",
  name: "SBI",
  kind: "bank",
  threshold: 50000,
  interest_to_date: 20000,
  interest_projected: 60000,
  crosses: true,
  tds_estimate: 6000,
  holdings: [],
  ...over,
});

const tax = (over: Partial<AnalyticsTax> = {}): AnalyticsTax => ({
  fy: "2026-27",
  fy_start: "2026-04-01",
  fy_end: "2027-03-31",
  as_of: "2026-11-04",
  is_current: true,
  available_fys: [],
  payers: [],
  totals: { interest_to_date: 31000, interest_projected: 52000, tds_estimate: 0 },
  savings: null,
  taxable: { interest_to_date: 31000, interest_projected: 52000 },
  tax_free: { interest_to_date: 0, interest_projected: 0, items: [] },
  excluded: { bonds: 0 },
  ...over,
});

describe("fy labels", () => {
  it("uses an en dash", () => {
    expect(fyDisplay("2026-27")).toBe("2026–27");
  });
  it("builds Title Case option labels", () => {
    expect(fyOptionLabel({ start_year: 2026, label: "2026-27", is_current: true })).toBe(
      "This FY 2026–27",
    );
    expect(fyOptionLabel({ start_year: 2025, label: "2025-26", is_current: false })).toBe(
      "Last FY 2025–26",
    );
  });
});

describe("barShare", () => {
  it("scales and caps at 100", () => {
    expect(barShare(25000, 50000)).toBe(50);
    expect(barShare(80000, 50000)).toBe(100);
  });
  it("is 0 for no interest or a bad threshold", () => {
    expect(barShare(0, 50000)).toBe(0);
    expect(barShare(100, 0)).toBe(0);
  });
});

describe("joinNames", () => {
  it("joins plainly", () => {
    expect(joinNames([])).toBe("");
    expect(joinNames(["SBI"])).toBe("SBI");
    expect(joinNames(["SBI", "HDFC Bank"])).toBe("SBI and HDFC Bank");
    expect(joinNames(["A", "B", "C"])).toBe("A, B and C");
  });
});

describe("interestSubline", () => {
  it("shows so far and expected for the current year", () => {
    expect(interestSubline(tax())).toBe("₹31,000 so far · about ₹52,000 by 31 Mar");
  });
  it("says full year for a past year", () => {
    expect(interestSubline(tax({ is_current: false }))).toBe("Full year");
  });
});

describe("tdsSentence", () => {
  it("names crossing payers and sums the TDS", () => {
    const payers = [
      payer(),
      payer({ key: "issuer:2", name: "HDFC Bank", tds_estimate: 200 }),
      payer({ key: "issuer:3", name: "Axis", crosses: false, tds_estimate: 0 }),
    ];
    expect(tdsSentence(payers, true)).toBe("SBI and HDFC Bank will deduct about ₹6,200 in TDS.");
    expect(tdsSentence(payers, false)).toBe("SBI and HDFC Bank deducted about ₹6,200 in TDS.");
  });
  it("has an empty-state sentence", () => {
    expect(tdsSentence([payer({ crosses: false })], true)).toBe(
      "No bank crosses its TDS limit this year.",
    );
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
  it("splits the bar by taxable share", () => {
    expect(taxableShare(75, 25)).toBe(75);
    expect(taxableShare(0, 0)).toBe(0);
  });
  it("says you pay more when tax exceeds TDS", () => {
    expect(slabSentence(100000, 10000, 30, true)).toBe(
      "At 30%, tax on ₹1,00,000 of taxable interest is about ₹31,200. Banks and issuers deduct ₹10,000, so you'd pay about ₹21,200 more when you file.",
    );
  });
  it("says you get money back when TDS exceeds tax", () => {
    expect(slabSentence(100000, 10000, 5, true)).toBe(
      "At 5%, tax on ₹1,00,000 of taxable interest is about ₹5,200. Banks and issuers deduct ₹10,000, so you'd get about ₹4,800 back.",
    );
  });
  it("handles the 0% slab", () => {
    expect(slabSentence(100000, 0, 0, true)).toBe("No tax on this interest at 0%.");
    expect(slabSentence(100000, 6000, 0, true)).toContain("₹6,000 in TDS, which you can claim back");
  });
  it("handles no TDS", () => {
    expect(slabSentence(100000, 0, 10, true)).toContain("No TDS is taken, so you'd pay about ₹10,400 more");
  });
  it("uses past tense for a past year", () => {
    expect(slabSentence(100000, 10000, 30, false)).toContain("Banks and issuers deducted ₹10,000");
  });
});

describe("bondsNote", () => {
  it("pluralises", () => {
    expect(bondsNote(1)).toBe("1 bond without coupon details isn't included.");
    expect(bondsNote(2)).toBe("2 bonds without coupon details aren't included.");
  });
});

describe("payerHint and savingsSentence", () => {
  it("describes the limit", () => {
    expect(payerHint(payer())).toBe("Over the ₹50,000 limit");
    expect(payerHint(payer({ crosses: false, threshold: 10000 }))).toBe("Limit ₹10,000");
  });
  it("says no TDS for payers without a limit", () => {
    expect(payerHint(payer({ threshold: null, crosses: false }))).toBe("No TDS");
  });
  it("mentions issuers when a bond payer is present", () => {
    const payers = [payer({ crosses: false }), payer({ kind: "bond", crosses: false })];
    expect(tdsSentence(payers, true)).toBe("No bank or issuer crosses its TDS limit this year.");
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
