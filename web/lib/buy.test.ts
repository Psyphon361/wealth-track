import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  BUY_DATE_BEFORE_LAST_SALE_ERROR,
  buyAmount,
  buyBody,
  buyDateError,
  buyNav,
  buyPath,
  buyUnits,
  canBuy,
  lastSaleDate,
  previewUnits,
  undoBuyPath,
} from "./buy";

const open = { status: "active" as const, settled: false, closed_on: null, exit: null };

describe("canBuy", () => {
  it("allows an open fund, also when partly sold", () => {
    expect(canBuy("mf", open)).toBe(true);
    expect(canBuy("mf", { ...open, exit: { kind: "sale" } })).toBe(true);
  });

  it("refuses closed funds and other types", () => {
    expect(canBuy("mf", { ...open, status: "sold", closed_on: "2026-01-01" })).toBe(false);
    expect(canBuy("stock", open)).toBe(false);
    expect(canBuy("fd", open)).toBe(false);
  });
});

describe("fields", () => {
  it("checks the amount like the API", () => {
    expect(z.safeParse(buyAmount, "5000.50").success).toBe(true);
    const bad = z.safeParse(buyAmount, "10.123");
    expect(bad.success ? "" : bad.error.issues[0].message).toBe("Up to 2 decimal places allowed");
    const zero = z.safeParse(buyAmount, "0");
    expect(zero.success ? "" : zero.error.issues[0].message).toBe("Must be greater than 0");
    const big = z.safeParse(buyAmount, "1000000001");
    expect(big.success ? "" : big.error.issues[0].message).toBe("Must be at most ₹100 crore");
  });

  it("allows up to 4 decimals for the NAV", () => {
    expect(z.safeParse(buyNav, "123.4567").success).toBe(true);
    const bad = z.safeParse(buyNav, "1.23456");
    expect(bad.success ? "" : bad.error.issues[0].message).toBe("Up to 4 decimal places allowed");
  });

  it("leaves blank units undefined and checks the rest", () => {
    expect(z.parse(buyUnits, "")).toBeUndefined();
    expect(z.parse(buyUnits, " 12.345 ")).toBe(12.345);
    const bad = z.safeParse(buyUnits, "1.2345");
    expect(bad.success ? "" : bad.error.issues[0].message).toBe("Up to 3 decimal places allowed");
    const big = z.safeParse(buyUnits, "10000001");
    expect(big.success ? "" : big.error.issues[0].message).toBe("Must be at most 1 crore");
  });
});

describe("dates", () => {
  it("refuses dates before the purchase date or the last sale", () => {
    expect(buyDateError("2026-01-01", "2026-02-01", null)).toBe("Date can't be before the purchase date");
    expect(buyDateError("2026-03-01", "2026-02-01", "2026-04-01")).toBe(BUY_DATE_BEFORE_LAST_SALE_ERROR);
    expect(buyDateError("2026-04-01", "2026-02-01", "2026-04-01")).toBeNull();
    expect(buyDateError("", "2026-02-01", null)).toBeNull();
  });

  it("reads the last sale date from the latest exit", () => {
    expect(lastSaleDate({ exit: { kind: "sale", date: "2026-05-05" } })).toBe("2026-05-05");
    expect(lastSaleDate({ exit: { kind: "maturity", date: "2026-05-05" } })).toBeNull();
    expect(lastSaleDate({ exit: null })).toBeNull();
  });
});

describe("units preview and body", () => {
  it("uses amount over NAV unless units are entered", () => {
    expect(previewUnits(5000, 40, null)).toBe(125);
    expect(previewUnits(1000, 3, null)).toBe(333.333);
    expect(previewUnits(5000, 40, 124.9)).toBe(124.9);
    expect(previewUnits(null, 40, null)).toBeNull();
    expect(previewUnits(5000, null, null)).toBeNull();
    expect(previewUnits(5000, 0, null)).toBeNull();
  });

  it("leaves units out of the body when blank", () => {
    expect(buyBody({ date: "2026-01-01", amount: 5000, nav: 40, units: undefined })).toEqual({
      date: "2026-01-01",
      amount: 5000,
      nav: 40,
    });
    expect(buyBody({ date: "2026-01-01", amount: 5000, nav: 40, units: 124.9 }).units).toBe(124.9);
  });

  it("builds the API paths", () => {
    expect(buyPath(7)).toBe("/holdings/mf/7/buy");
    expect(undoBuyPath(7, 3)).toBe("/holdings/mf/7/buys/3");
  });
});
