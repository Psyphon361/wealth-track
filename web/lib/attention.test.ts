import { describe, expect, it } from "vitest";
import {
  attentionToggleLabel,
  attentionTotal,
  daysLeftText,
  dueText,
  holdingHref,
  lastUpdatedText,
  maturingAmountText,
  maturingLine,
  rateText,
  sipHref,
  visibleRows,
} from "./attention";

describe("attention helpers", () => {
  it("sums the true counts", () => {
    const a = {
      maturing: [],
      stale: [],
      sips: [],
      counts: { maturing: 25, stale: 2, sips: 1 },
    };
    expect(attentionTotal(a)).toBe(28);
  });

  it("slices rows to three unless expanded", () => {
    const rows = [1, 2, 3, 4, 5];
    expect(visibleRows(rows, false)).toEqual([1, 2, 3]);
    expect(visibleRows(rows, true)).toEqual(rows);
  });

  it("toggle label only when more than three", () => {
    expect(attentionToggleLabel(3, false)).toBeNull();
    expect(attentionToggleLabel(5, false)).toBe("Show All 5");
    expect(attentionToggleLabel(5, true)).toBe("Show Less");
  });

  it("days left text", () => {
    expect(daysLeftText(0)).toBe("Today");
    expect(daysLeftText(1)).toBe("Tomorrow");
    expect(daysLeftText(12)).toBe("In 12 days");
  });

  it("maturing line and amount", () => {
    expect(maturingLine("2027-01-07", 12)).toBe("Matures 7 Jan 2027 · In 12 days");
    expect(maturingAmountText(null, true)).toBe("—");
    expect(maturingAmountText(100000, false)).toContain("1,00,000");
    expect(maturingAmountText(100000, true).startsWith("~")).toBe(true);
  });

  it("rate, dates and links", () => {
    expect(rateText(7.25)).toBe("7.25% p.a.");
    expect(rateText(null)).toBeNull();
    expect(lastUpdatedText("2026-01-07")).toBe("Last updated 7 Jan 2026");
    expect(dueText("2026-11-12")).toBe("Due 12 Nov 2026");
    expect(holdingHref("fd", 4)).toBe("/portfolio/fd/4");
    expect(sipHref(9)).toBe("/portfolio/mf/9");
    expect(sipHref(null)).toBeNull();
  });
});
