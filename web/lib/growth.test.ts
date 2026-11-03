import { describe, expect, it } from "vitest";
import {
  changeSentence,
  columnLabel,
  dateRangeLabel,
  monthColumns,
  monthLabel,
  monthsSummary,
  signOf,
  signedWhole,
  splitShares,
} from "./growth";

describe("monthLabel", () => {
  it("formats YYYY-MM", () => {
    expect(monthLabel("2026-11")).toBe("Nov 2026");
    expect(monthLabel("2026-01")).toBe("Jan 2026");
  });
});

describe("signOf and signedWhole", () => {
  it("returns the sign", () => {
    expect(signOf(3)).toBe("+");
    expect(signOf(-3)).toBe("-");
    expect(signOf(0)).toBe("");
  });

  it("formats whole rupees with Indian grouping", () => {
    expect(signedWhole(260970.4)).toBe("+₹2,60,970");
    expect(signedWhole(-25780)).toBe("-₹25,780");
    expect(signedWhole(0.2)).toBe("₹0");
  });
});

describe("changeSentence", () => {
  it("covers put in and grew", () => {
    expect(changeSentence(201620, 59351)).toBe(
      "You put in ₹2,01,620 and your investments grew ₹59,351.",
    );
  });
  it("covers fell", () => {
    expect(changeSentence(201620, -25780)).toBe(
      "You put in ₹2,01,620 and your investments fell ₹25,780.",
    );
  });
  it("covers took out", () => {
    expect(changeSentence(-2682, 100)).toBe("You took out ₹2,682 and your investments grew ₹100.");
  });
  it("covers zero new money and zero growth", () => {
    expect(changeSentence(0, 500)).toBe("Your investments grew ₹500.");
    expect(changeSentence(0, -500)).toBe("Your investments fell ₹500.");
    expect(changeSentence(500, 0)).toBe("You put in ₹500.");
    expect(changeSentence(0, 0)).toBe("No change in this period.");
    expect(changeSentence(0.1, -0.2)).toBe("No change in this period.");
  });
});

describe("splitShares", () => {
  it("uses absolute values and sums to 100", () => {
    expect(splitShares(75, 25)).toEqual({ money: 75, growth: 25 });
    expect(splitShares(-75, -25)).toEqual({ money: 75, growth: 25 });
    expect(splitShares(50, -50)).toEqual({ money: 50, growth: 50 });
  });
  it("is zero when both are zero", () => {
    expect(splitShares(0, 0)).toEqual({ money: 0, growth: 0 });
  });
});

describe("dateRangeLabel", () => {
  it("omits the year inside one year", () => {
    expect(dateRangeLabel("2026-10-31", "2026-11-03")).toBe("31 Oct – 3 Nov");
  });
  it("adds the year across years", () => {
    expect(dateRangeLabel("2025-12-31", "2026-01-03")).toBe("31 Dec 2025 – 3 Jan 2026");
  });
});

describe("columnLabel", () => {
  it("shows the year on January and the first column", () => {
    expect(columnLabel("2026-01", false)).toEqual({ month: "Jan", year: 2026 });
    expect(columnLabel("2025-12", true)).toEqual({ month: "Dec", year: 2025 });
    expect(columnLabel("2026-03", false)).toEqual({ month: "Mar", year: null });
  });
});

describe("monthColumns", () => {
  it("orders oldest first and stacks around a zero baseline", () => {
    const { columns, zero } = monthColumns([
      { month: "2026-02", new_money: 50, growth: -50 },
      { month: "2026-01", new_money: 100, growth: 100 },
    ]);
    expect(columns.map((c) => c.month)).toEqual(["2026-01", "2026-02"]);
    // up max 200, down max 50 -> total 250, zero at 20%
    expect(zero).toBeCloseTo(20);
    const [jan, feb] = columns;
    expect(jan.segments[0]).toMatchObject({ kind: "money", bottom: zero });
    expect(jan.segments[0].height).toBeCloseTo(40);
    expect(jan.segments[1].bottom).toBeCloseTo(zero + 40);
    expect(feb.segments[1].bottom).toBeCloseTo(zero - 20);
    expect(feb.segments[1].height).toBeCloseTo(20);
  });

  it("gives non-zero segments a minimum height and zero ones none", () => {
    const { columns } = monthColumns([
      { month: "2026-01", new_money: 1, growth: 0 },
      { month: "2026-02", new_money: 1e9, growth: 0 },
    ]);
    expect(columns[0].segments[0].height).toBeGreaterThan(0);
    expect(columns[0].segments[1].height).toBe(0);
  });

  it("handles all zeros", () => {
    const { columns, zero } = monthColumns([{ month: "2026-01", new_money: 0, growth: 0 }]);
    expect(zero).toBe(0);
    expect(columns[0].segments.every((s) => s.height === 0)).toBe(true);
  });
});

describe("monthsSummary", () => {
  it("sums money and growth and averages money over 12 months", () => {
    const s = monthsSummary([
      { new_money: 1200, growth: 50 },
      { new_money: 600, growth: -20 },
    ]);
    expect(s.newMoney).toBe(1800);
    expect(s.growth).toBe(30);
    expect(s.perMonth).toBe(150);
  });
});
