import { describe, expect, it } from "vitest";
import { chartDomain, rangeGrowth } from "./networth-range";

describe("rangeGrowth", () => {
  it("is null with fewer than 2 points", () => {
    expect(rangeGrowth([])).toBeNull();
    expect(rangeGrowth([{ invested: 1, current: 2 }])).toBeNull();
  });

  it("is the change in gain between first and last", () => {
    expect(
      rangeGrowth([
        { invested: 100, current: 110 },
        { invested: 120, current: 150 },
      ]),
    ).toBe(20);
  });

  it("can be negative", () => {
    expect(
      rangeGrowth([
        { invested: 100, current: 120 },
        { invested: 100, current: 90 },
      ]),
    ).toBe(-30);
  });
});

describe("chartDomain", () => {
  it("pads the span by 8%", () => {
    const [lo, hi] = chartDomain([
      { invested: 1000, current: 1100 },
      { invested: 1000, current: 1200 },
    ]);
    expect(lo).toBeCloseTo(984);
    expect(hi).toBeCloseTo(1216);
  });

  it("uses 2% of the value when the span is 0", () => {
    const [lo, hi] = chartDomain([{ invested: 1000, current: 1000 }]);
    expect(lo).toBeCloseTo(980);
    expect(hi).toBeCloseTo(1020);
  });

  it("floors the lower bound at 0", () => {
    const [lo] = chartDomain([
      { invested: 0, current: 10 },
      { invested: 0, current: 1000 },
    ]);
    expect(lo).toBe(0);
  });
});
