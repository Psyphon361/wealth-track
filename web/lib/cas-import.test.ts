import { describe, expect, it } from "vitest";
import { defaultSelected, rowAction, updateBlocked } from "./cas-import";
import type { CasPreviewRow } from "./types";

function row(key: string, sales: boolean[], importable = true): CasPreviewRow {
  return {
    key,
    importable,
    existing: sales.map((has_sales, i) => ({
      id: i + 1,
      units: 1,
      invested_amount: 1,
      avg_nav: 1,
      purchase_date: "2024-01-01",
      has_sales,
    })),
  } as unknown as CasPreviewRow;
}

describe("updateBlocked", () => {
  it("blocks only a single match with sales", () => {
    expect(updateBlocked(row("a", [true]))).toBe(true);
    expect(updateBlocked(row("a", [false]))).toBe(false);
    expect(updateBlocked(row("a", []))).toBe(false);
    expect(updateBlocked(row("a", [true, false]))).toBe(false);
  });
});

describe("rowAction", () => {
  it("defaults to update for one clean match", () => {
    expect(rowAction(row("a", [false]))).toBe("update");
    expect(rowAction(row("a", [false]), "create")).toBe("create");
  });
  it("forces add as new when sales are recorded", () => {
    expect(rowAction(row("a", [true]))).toBe("create");
    expect(rowAction(row("a", [true]), "update")).toBe("create");
  });
  it("adds as new when nothing or several match", () => {
    expect(rowAction(row("a", []))).toBe("create");
    expect(rowAction(row("a", [false, false]), "update")).toBe("create");
  });
});

describe("defaultSelected", () => {
  it("skips rows that can't be updated and rows that can't be imported", () => {
    const rows = [
      row("clean", [false]),
      row("new", []),
      row("sold", [true]),
      row("bad", [], false),
      row("multi", [true, false]),
    ];
    expect([...defaultSelected(rows)]).toEqual(["clean", "new", "multi"]);
  });
});
