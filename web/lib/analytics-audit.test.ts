import { describe, expect, it } from "vitest";
import { returnBars } from "./returns";

const EPS = 1e-9;

describe("returnBars audit", () => {
  it("scales positive and negative values on one axis within the track", () => {
    const bars = returnBars([10, -30, null, 0, 20]);
    expect(bars[2]).toBeNull();
    // span 50, zero at 60
    expect(bars[0]).toMatchObject({ left: 60, width: 20, zero: 60 });
    expect(bars[1]).toMatchObject({ width: 60, zero: 60 });
    expect(bars[1]!.left).toBeCloseTo(0);
    expect(bars[3]).toMatchObject({ left: 60, width: 0 });
    expect(bars[4]).toMatchObject({ left: 60, width: 40 });
    for (const b of bars) {
      if (!b) continue;
      expect(b.left).toBeGreaterThanOrEqual(-EPS);
      expect(b.left + b.width).toBeLessThanOrEqual(100 + EPS);
    }
  });

  it("all-negative puts zero at the right edge", () => {
    const bars = returnBars([-10, -20]);
    expect(bars[0]).toMatchObject({ zero: 100 });
    expect(bars[1]!.left).toBeCloseTo(0);
    expect(bars[1]!.width).toBeCloseTo(100);
    expect(bars[0]!.left).toBeCloseTo(50);
  });

  it("all-positive puts zero at the left edge; nulls and zeros give empty/flat bars", () => {
    const bars = returnBars([5, 10]);
    expect(bars[1]).toMatchObject({ left: 0, width: 100, zero: 0 });
    expect(returnBars([null, null])).toEqual([null, null]);
    expect(returnBars([0, null])).toEqual([{ left: 0, width: 0, zero: 0 }, null]);
    expect(returnBars([])).toEqual([]);
  });

  it("a tiny non-zero return still has a positive width next to a large one", () => {
    const bars = returnBars([0.01, 500]);
    expect(bars[0]!.width).toBeGreaterThan(0);
  });
});
