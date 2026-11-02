import { describe, expect, it } from "vitest";
import { allocationSlices } from "./allocation";

const row = (type: string, current: number) => ({
  type,
  label: type.toUpperCase(),
  current,
  allocation_pct: current,
});

describe("allocationSlices", () => {
  it("drops zero-value types and sorts descending", () => {
    const s = allocationSlices([row("a", 10), row("b", 0), row("c", 30)]);
    expect(s.map((x) => x.key)).toEqual(["c", "a"]);
  });

  it("shows all six when exactly six exist", () => {
    const s = allocationSlices([1, 2, 3, 4, 5, 6].map((n) => row(`t${n}`, n)));
    expect(s).toHaveLength(6);
    expect(s.some((x) => x.key === "more")).toBe(false);
  });

  it("folds the tail into More when more than six exist", () => {
    const s = allocationSlices([1, 2, 3, 4, 5, 6, 7, 8].map((n) => row(`t${n}`, n)));
    expect(s).toHaveLength(6);
    expect(s.slice(0, 5).map((x) => x.key)).toEqual(["t8", "t7", "t6", "t5", "t4"]);
    expect(s[5]).toMatchObject({ key: "more", label: "More", value: 6, pct: 6, folded: 3 });
  });
});
