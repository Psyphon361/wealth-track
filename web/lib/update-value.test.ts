import { describe, expect, it } from "vitest";
import {
  cashUpdateSchema,
  moneyUpdateSchema,
  npsUpdateSchema,
  CASH_BALANCE_NEGATIVE_ERROR,
  MAX_MONEY_ERROR,
} from "../components/forms/schema";
import {
  amountBody,
  amountDefaults,
  amountLabel,
  canUpdateValue,
  currentFigureText,
  npsBody,
  npsDefaults,
  updateValueLabel,
} from "./update-value";

const open = { status: "active" as const, settled: false, closed_on: null, exit: null };
const sold = { ...open, status: "sold" as const, closed_on: "2026-01-15" };

describe("update value helpers", () => {
  it("labels the action per type", () => {
    expect(updateValueLabel("cash")).toBe("Update Balance");
    expect(updateValueLabel("pf")).toBe("Update Balance");
    expect(updateValueLabel("other")).toBe("Update Value");
    expect(updateValueLabel("nps")).toBe("Update Units");
    expect(updateValueLabel("stock")).toBeNull();
  });

  it("hides the action for other types and closed holdings", () => {
    expect(canUpdateValue("cash", open)).toBe(true);
    expect(canUpdateValue("other", sold)).toBe(false);
    expect(canUpdateValue("fd", open)).toBe(false);
  });

  it("pre-fills current values and today's date", () => {
    expect(amountDefaults("cash", { balance: 1500.5 }, "2026-11-10")).toEqual({
      amount: "1500.5",
      date: "2026-11-10",
    });
    expect(amountDefaults("other", { current_value: 900 }, "2026-11-10").amount).toBe("900");
    expect(npsDefaults({ units: 12.3456, contributed: 5000 })).toEqual({
      units: "12.3456",
      contributed: "5000",
    });
  });

  it("builds the request bodies", () => {
    expect(amountBody("cash", 10, "2026-11-10")).toEqual({
      balance: 10,
      balance_date: "2026-11-10",
    });
    expect(amountBody("pf", 10, "2026-11-10")).toEqual({
      balance: 10,
      balance_date: "2026-11-10",
    });
    expect(amountBody("other", 10, "2026-11-10")).toEqual({
      current_value: 10,
      value_date: "2026-11-10",
    });
    expect(npsBody(1.5, 200)).toEqual({ units: 1.5, contributed: 200 });
    expect(amountLabel("other")).toBe("Current Value");
    expect(amountLabel("cash")).toBe("Balance");
  });

  it("describes the current figure", () => {
    expect(currentFigureText("cash", { balance: 1000, balance_date: "2026-01-05" })).toContain(
      "as of",
    );
    expect(currentFigureText("nps", { units: 2, contributed: 1000 })).toContain("2.0000 units");
  });
});

describe("update value schemas", () => {
  it("cash allows 0 but not negatives", () => {
    expect(cashUpdateSchema.safeParse({ amount: "0", date: "2026-11-10" }).success).toBe(true);
    const r = cashUpdateSchema.safeParse({ amount: "-1", date: "2026-11-10" });
    expect(r.success).toBe(false);
    expect(r.error?.issues[0].message).toBe(CASH_BALANCE_NEGATIVE_ERROR);
  });

  it("pf and other need more than 0 and at most 100 crore", () => {
    expect(moneyUpdateSchema.safeParse({ amount: "0", date: "2026-11-10" }).success).toBe(false);
    const r = moneyUpdateSchema.safeParse({ amount: "2000000000", date: "2026-11-10" });
    expect(r.error?.issues[0].message).toBe(MAX_MONEY_ERROR);
  });

  it("rejects a blank or too early date", () => {
    expect(moneyUpdateSchema.safeParse({ amount: "5", date: "" }).success).toBe(false);
    expect(moneyUpdateSchema.safeParse({ amount: "5", date: "1980-01-01" }).success).toBe(false);
  });

  it("nps units allow 4 decimals, not 5", () => {
    expect(npsUpdateSchema.safeParse({ units: "1.2345", contributed: "10" }).success).toBe(true);
    const r = npsUpdateSchema.safeParse({ units: "1.23456", contributed: "10" });
    expect(r.error?.issues[0].message).toBe("Up to 4 decimal places allowed");
    expect(npsUpdateSchema.safeParse({ units: "1", contributed: "0" }).success).toBe(false);
  });
});
