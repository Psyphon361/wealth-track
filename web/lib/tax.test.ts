import { describe, expect, it } from "vitest";
import {
  barShare,
  fyDisplay,
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

describe("payerHint and savingsSentence", () => {
  it("describes the limit", () => {
    expect(payerHint(payer())).toBe("Over the ₹50,000 limit");
    expect(payerHint(payer({ crosses: false, threshold: 10000 }))).toBe("Limit ₹10,000");
  });
  it("pluralises accounts", () => {
    expect(savingsSentence({ interest_estimate: 1200, accounts: 1 })).toContain("1 account.");
    expect(savingsSentence({ interest_estimate: 1200, accounts: 2 })).toContain("2 accounts.");
  });
});
