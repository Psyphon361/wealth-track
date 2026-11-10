import { describe, expect, it } from "vitest";
import {
  bucketLabel,
  bucketRateText,
  daysLeftText,
  excludedNotes,
  flagSentences,
  hasMore,
  progressPercent,
  roomSentence,
  splitPercents,
  splitSubline,
  unrealisedPath,
  visibleItems,
} from "./unrealised";

describe("unrealisedPath", () => {
  it("adds the fy only when given", () => {
    expect(unrealisedPath()).toBe("/analytics/unrealised");
    expect(unrealisedPath(2025)).toBe("/analytics/unrealised?fy=2025");
  });
});

describe("splitPercents", () => {
  it("splits by size", () => {
    expect(splitPercents(25, 75)).toEqual({ short: 25, long: 75 });
  });
  it("ignores sign and handles zero", () => {
    expect(splitPercents(-50, 50)).toEqual({ short: 50, long: 50 });
    expect(splitPercents(0, 0)).toEqual({ short: 0, long: 0 });
  });
});

describe("progressPercent", () => {
  it("clamps between 0 and 100", () => {
    expect(progressPercent(50000, 125000)).toBe(40);
    expect(progressPercent(200000, 125000)).toBe(100);
    expect(progressPercent(-5, 125000)).toBe(0);
    expect(progressPercent(5, 0)).toBe(0);
  });
});

describe("visibleItems", () => {
  const items = [1, 2, 3, 4, 5, 6, 7];
  it("shows 5 until expanded", () => {
    expect(visibleItems(items, false)).toEqual([1, 2, 3, 4, 5]);
    expect(visibleItems(items, true)).toHaveLength(7);
    expect(hasMore(items)).toBe(true);
    expect(hasMore([1, 2, 3])).toBe(false);
  });
});

describe("daysLeftText", () => {
  it("words the days", () => {
    expect(daysLeftText(1)).toBe("1 day left");
    expect(daysLeftText(30)).toBe("30 days left");
    expect(daysLeftText(0)).toBe("Today");
  });
});

describe("labels and sentences", () => {
  it("labels buckets and rates", () => {
    expect(bucketLabel("equity_lt")).toBe("Equity, Long Term");
    expect(bucketLabel(null)).toBe("Not Counted");
    expect(bucketRateText(null)).toBe("Your Slab");
    expect(bucketRateText(12.5)).toBe("12.5%");
  });
  it("words the headline and room as facts", () => {
    expect(splitSubline({ short_term_net: 1000, long_term_net: -500 })).toContain("short term");
    expect(roomSentence(125000)).toContain("can be booked tax-free");
    expect(roomSentence(125000)).not.toMatch(/should|sell|harvest/i);
  });
  it("gives one sentence per distinct flag", () => {
    const out = flagSentences([
      { flags: ["grandfathering", "estimated"] },
      { flags: ["grandfathering"] },
    ]);
    expect(out).toHaveLength(2);
  });
  it("notes excluded counts", () => {
    expect(excludedNotes({ at_cost: 0, no_invested_amount: 0, bonds_no_face: 0, no_purchase_date: 0 })).toEqual([]);
    const notes = excludedNotes({ at_cost: 2, no_invested_amount: 1, bonds_no_face: 1, no_purchase_date: 1 }, 3);
    expect(notes).toHaveLength(5);
    expect(notes[0]).toContain("2 holdings are valued at cost");
  });
});
