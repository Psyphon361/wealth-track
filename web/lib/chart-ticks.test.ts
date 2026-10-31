import { describe, expect, it } from "vitest";
import { formatDateShortMonth, pickTicks, tickLabel } from "./chart-ticks";
import { isStale, STALE_MS } from "./networth-cache";

describe("labels", () => {
  it("uses Sep, not Sept", () => {
    expect(formatDateShortMonth("2026-09-23")).toBe("23 Sep 2026");
    expect(tickLabel("2026-09-05", "1y")).toBe("Sep 26");
    expect(tickLabel("2026-03-12", "1m")).toBe("12 Mar");
  });
});

describe("pickTicks", () => {
  const days = (start: string, n: number) => {
    const out: string[] = [];
    const d = new Date(start + "T00:00:00Z");
    for (let i = 0; i < n; i++) {
      out.push(d.toISOString().slice(0, 10));
      d.setUTCDate(d.getUTCDate() + 1);
    }
    return out;
  };
  it("skips 1M", () => {
    expect(pickTicks(days("2026-09-01", 30), "1m")).toBeUndefined();
  });
  it("has one tick per month, no duplicates, at most 8", () => {
    const ticks = pickTicks(days("2026-01-01", 200), "6m")!;
    expect(ticks.length).toBeLessThanOrEqual(8);
    const labels = ticks.map((t) => tickLabel(t, "6m"));
    expect(new Set(labels).size).toBe(labels.length);
  });
  it("widens for long All ranges", () => {
    const ticks = pickTicks(days("2020-01-01", 365 * 6), "all")!;
    expect(ticks.length).toBeLessThanOrEqual(8);
    const labels = ticks.map((t) => tickLabel(t, "all"));
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("isStale", () => {
  it("is stale after 5 minutes", () => {
    expect(isStale(0, STALE_MS)).toBe(false);
    expect(isStale(0, STALE_MS + 1)).toBe(true);
  });
});
