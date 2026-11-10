import { describe, expect, it } from "vitest";
import {
  compareFootnote,
  compareRows,
  compareSentence,
  excludedText,
  groupDetail,
  overallHeadline,
  overallSentence,
  pct1,
  returnBars,
  signedPct1,
  signedWhole,
  sinceLabel,
} from "./returns";
import type { ReturnGroup, ReturnsBenchmark } from "./types";

const group = (over: Partial<ReturnGroup> = {}): ReturnGroup => ({
  key: "all",
  label: "All",
  holdings: 3,
  invested: 453000,
  current: 510000,
  gain: 57000,
  return_pct: 12.37,
  annualised: true,
  basis: null,
  since: "2024-03-15",
  ...over,
});

const bench = (over: Partial<ReturnsBenchmark> = {}): ReturnsBenchmark => ({
  label: "Nifty 50 index fund",
  scheme_name: "UTI Nifty 50 Index Fund",
  nav_date: "2026-11-02",
  equity: { your_pct: 14.2, benchmark_pct: 12.1, annualised: true },
  overall: null,
  fd_rate: 7.1,
  inflation_pct: 4.5,
  inflation_period: "Oct 2025 to Oct 2026",
  ...over,
});

describe("returnBars", () => {
  it("scales positives from zero", () => {
    const [a, b] = returnBars([10, 5]);
    expect(a).toEqual({ left: 0, width: 100, zero: 0 });
    expect(b?.width).toBe(50);
  });
  it("puts negatives left of the zero line", () => {
    const [a, b] = returnBars([10, -10]);
    expect(a).toEqual({ left: 50, width: 50, zero: 50 });
    expect(b).toEqual({ left: 0, width: 50, zero: 50 });
  });
  it("keeps nulls and handles all zero", () => {
    expect(returnBars([null, 0])).toEqual([null, { left: 0, width: 0, zero: 0 }]);
  });
});

describe("percent and money text", () => {
  it("one decimal", () => {
    expect(pct1(12.37)).toBe("12.4%");
    expect(signedPct1(-3.14)).toBe("−3.1%");
    expect(signedPct1(5)).toBe("+5.0%");
    expect(signedWhole(-57000)).toBe("−₹57,000");
  });
});

describe("overall", () => {
  it("headline", () => {
    expect(overallHeadline(group())).toEqual({ value: "12.4%", suffix: "a year" });
    expect(overallHeadline(group({ annualised: false }))?.suffix).toBe("in under a year");
    expect(overallHeadline(group({ return_pct: null }))).toBeNull();
  });
  it("sentence gain and loss", () => {
    expect(overallSentence(group())).toBe(
      "₹4,53,000 invested is now worth ₹5,10,000, a gain of ₹57,000.",
    );
    expect(overallSentence(group({ current: 400000, gain: -53000 }))).toBe(
      "₹4,53,000 invested is now worth ₹4,00,000, a loss of ₹53,000.",
    );
  });
  it("since and detail", () => {
    expect(sinceLabel("2024-03-15")).toBe("Since Mar 2024");
    expect(groupDetail(group())).toBe("Gain ₹57,000 on ₹4,53,000 invested");
    expect(groupDetail(group({ gain: -10 }))).toBe("Loss ₹10 on ₹4,53,000 invested");
  });
});

describe("comparison", () => {
  it("sentence uses equity, then overall, else null", () => {
    expect(compareSentence(bench())).toBe(
      "Your equity earned 14.2% a year. A Nifty 50 index fund on the same dates earned 12.1%.",
    );
    expect(
      compareSentence(
        bench({ equity: null, overall: { your_pct: 8, benchmark_pct: 9, annualised: false } }),
      ),
    ).toBe(
      "Your money earned 8.0% in under a year. A Nifty 50 index fund on the same dates earned 9.0%.",
    );
    expect(compareSentence(bench({ equity: null }))).toBeNull();
    expect(compareSentence(null)).toBeNull();
  });
  it("rows omit nulls", () => {
    expect(compareRows(bench()).map((r) => r.key)).toEqual(["you", "nifty", "fd", "inflation"]);
    expect(compareRows(bench({ fd_rate: null, inflation_pct: null, equity: null }))).toEqual([]);
    expect(compareRows(null)).toEqual([]);
  });
  it("footnote", () => {
    expect(compareFootnote(bench(), () => "2 Nov 2026")).toBe(
      "Nifty figure replays your own investment dates into UTI Nifty 50 Index Fund (NAV as of 2 Nov 2026).",
    );
    expect(compareFootnote(bench({ nav_date: null }), () => "x")).toBe(
      "Nifty figure replays your own investment dates into UTI Nifty 50 Index Fund.",
    );
  });
});

describe("footnotes", () => {
  it("excluded", () => {
    expect(excludedText({ at_cost: 0, no_flows: 0, other_without_invested: 0 })).toBeNull();
    expect(excludedText({ at_cost: 0, no_flows: 4, other_without_invested: 0 })).toBe(
      "Not in returns: 4 holdings with no dated investments (cash, EPF/PPF, NPS).",
    );
    expect(excludedText({ at_cost: 1, no_flows: 0, other_without_invested: 2 })).toBe(
      "Not in returns: 1 holding valued at cost and 2 Other holdings without an amount invested.",
    );
    expect(excludedText({ at_cost: 2, no_flows: 3, other_without_invested: 1 })).toBe(
      "Not in returns: 3 holdings with no dated investments (cash, EPF/PPF, NPS), 2 holdings valued at cost and 1 Other holding without an amount invested.",
    );
  });
});
