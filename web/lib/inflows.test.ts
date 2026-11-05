import { describe, expect, it } from "vitest";
import {
  defaultMonth,
  filterInflows,
  inflowColumns,
  inflowHref,
  inflowTotals,
  inflowTypeLabel,
  inflowsPath,
  sortedItems,
  type InflowMonth,
} from "./inflows";

const months: InflowMonth[] = [
  {
    month: "2026-11",
    interest: 0,
    principal: 0,
    items: [],
  },
  {
    month: "2026-12",
    interest: 150,
    principal: 1000,
    items: [
      { date: "2026-12-20", type: "fd", id: 2, name: "FD B", kind: "maturity", interest: 100, principal: 1000 },
      { date: "2026-12-05", type: "bond", id: 7, name: "Bond A", kind: "coupon", interest: 50, principal: 0 },
    ],
  },
  {
    month: "2027-01",
    interest: 0,
    principal: 500,
    items: [
      { date: "2027-01-10", type: "bond", id: 7, name: "Bond A", kind: "redemption", interest: 0, principal: 500 },
    ],
  },
];

describe("filterInflows", () => {
  it("keeps everything for all types, principal included", () => {
    const out = filterInflows(months, "all", false);
    expect(inflowTotals(out)).toEqual({ interest: 150, principal: 1500 });
  });

  it("filters by type and recomputes month totals", () => {
    const out = filterInflows(months, "bond", false);
    expect(out[1]).toMatchObject({ interest: 50, principal: 0 });
    expect(out[2]).toMatchObject({ interest: 0, principal: 500 });
  });

  it("interest only zeroes principal and drops items with no interest", () => {
    const out = filterInflows(months, "all", true);
    expect(inflowTotals(out)).toEqual({ interest: 150, principal: 0 });
    expect(out[1].items).toHaveLength(2);
    expect(out[2].items).toHaveLength(0);
  });

  it("keeps empty months", () => {
    expect(filterInflows(months, "rd", false)).toHaveLength(3);
  });
});

describe("inflowColumns", () => {
  it("scales to the tallest month", () => {
    const cols = inflowColumns(months);
    expect(cols[1].interestPct + cols[1].principalPct).toBeCloseTo(100);
    expect(cols[2].principalPct).toBeCloseTo((500 / 1150) * 100);
    expect(cols[0]).toMatchObject({ interestPct: 0, principalPct: 0 });
  });

  it("is all zero when nothing is coming in", () => {
    const cols = inflowColumns([{ month: "2026-11", interest: 0, principal: 0, items: [] }]);
    expect(cols[0].interestPct).toBe(0);
  });
});

describe("helpers", () => {
  it("defaultMonth picks the first month with money", () => {
    expect(defaultMonth(months)).toBe("2026-12");
    expect(defaultMonth([])).toBeNull();
  });

  it("sortedItems orders by date", () => {
    expect(sortedItems(months[1]).map((i) => i.name)).toEqual(["Bond A", "FD B"]);
    expect(sortedItems(undefined)).toEqual([]);
  });

  it("builds links, paths and labels", () => {
    expect(inflowHref(months[1].items[0])).toBe("/portfolio/fd/2");
    expect(inflowsPath(24)).toBe("/analytics/inflows?months=24");
    expect(inflowTypeLabel("fd")).toBe("Fixed Deposits");
    expect(inflowTypeLabel("crypto")).toBe("Crypto");
  });
});
