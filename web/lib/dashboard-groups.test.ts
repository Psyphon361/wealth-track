import { describe, expect, it } from "vitest";
import { groupRows, type GroupRow } from "./dashboard-groups";

const row = (type: string, o: Partial<GroupRow> = {}): GroupRow => ({
  type,
  label: type,
  count: 1,
  matured_count: 0,
  invested: 100,
  current: 110,
  allocation_pct: 10,
  gain: 10,
  gain_pct: 10,
  day_change: null,
  ...o,
});

describe("groupRows", () => {
  it("hides empty types and drops empty groups", () => {
    const g = groupRows([row("fd"), row("rd", { count: 0 }), row("stock")]);
    expect(g.map((x) => x.name)).toEqual(["Deposits", "Market-linked"]);
    expect(g[0].rows.map((r) => r.type)).toEqual(["fd"]);
  });

  it("keeps a type with only matured holdings", () => {
    const g = groupRows([row("fd", { count: 0, matured_count: 2 }), row("stock")]);
    expect(g[0].rows).toHaveLength(1);
  });

  it("computes subtotals with null handling", () => {
    const g = groupRows([
      row("fd", { gain: 10, day_change: null }),
      row("cash", { gain: null, gain_pct: null, invested: 500 }),
      row("stock"),
    ]);
    const s = g[0].subtotal;
    expect(s.count).toBe(2);
    expect(s.invested).toBe(600);
    expect(s.allocation_pct).toBe(20);
    expect(s.gain).toBe(10);
    expect(s.gain_pct).toBe(10);
    expect(s.day_change).toBeNull();
  });

  it("returns null gain when all null", () => {
    const g = groupRows([row("fd", { gain: null, gain_pct: null }), row("stock")]);
    expect(g[0].subtotal.gain).toBeNull();
    expect(g[0].subtotal.gain_pct).toBeNull();
  });

  it("sums day change of non-null rows", () => {
    const g = groupRows([
      row("stock", { day_change: 5 }),
      row("mf", { day_change: -2 }),
      row("fd"),
    ]);
    expect(g[1].subtotal.day_change).toBe(3);
  });

  it("hides subtotal when one group only", () => {
    const g = groupRows([row("fd"), row("rd")]);
    expect(g).toHaveLength(1);
    expect(g[0].showSubtotal).toBe(false);
    expect(groupRows([row("fd"), row("stock")])[0].showSubtotal).toBe(true);
  });
});
