import { describe, expect, it } from "vitest";
import { canEdit, isClosed, isSoldInPart, readOnlyFields } from "./edit-guards";

const active = { status: "active" as const, settled: false, closed_on: null, exit: null };
const partly = { ...active, exit: { kind: "sale" as const } };
const sold = { ...partly, status: "sold" as const, closed_on: "2026-01-15" };
const settled = {
  status: "matured" as const,
  settled: true,
  closed_on: null,
  exit: { kind: "maturity" as const },
};
const matured = { ...active, status: "matured" as const };

describe("edit guards", () => {
  it("closes sold and settled holdings only", () => {
    expect(isClosed(sold)).toBe(true);
    expect(isClosed(settled)).toBe(true);
    expect(isClosed(matured)).toBe(false);
    expect(isClosed(partly)).toBe(false);
    expect(canEdit(sold)).toBe(false);
    expect(canEdit(settled)).toBe(false);
    expect(canEdit(matured)).toBe(true);
    expect(canEdit(active)).toBe(true);
  });

  it("is sold in part when a sale exists and the holding is open", () => {
    expect(isSoldInPart(partly)).toBe(true);
    expect(isSoldInPart(active)).toBe(false);
    expect(isSoldInPart(sold)).toBe(false);
  });

  it("locks the quantity, cost and date fields per type", () => {
    expect(readOnlyFields("stock", partly)).toEqual(["quantity", "avg_buy_price", "buy_date"]);
    expect(readOnlyFields("bond", partly)).toEqual([
      "quantity",
      "purchase_price",
      "invested_amount",
      "purchase_date",
    ]);
    expect(readOnlyFields("mf", partly)).toEqual([
      "units",
      "avg_nav",
      "invested_amount",
      "purchase_date",
    ]);
    expect(readOnlyFields("gold", partly)).toEqual(["weight_grams", "invested_amount", "purchase_date"]);
    expect(readOnlyFields("other", partly)).toEqual(["invested_amount", "acquired_on"]);
  });

  it("locks nothing otherwise", () => {
    expect(readOnlyFields("stock", active)).toEqual([]);
    expect(readOnlyFields("fd", partly)).toEqual([]);
  });
});
