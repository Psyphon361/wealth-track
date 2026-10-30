import { describe, expect, it } from "vitest";
import {
  BOND_PRECISION,
  MF_PRECISION,
  bondAmountsConsistent,
  deriveAmount,
  mfAmountsConsistent,
  type AmountField,
  type Amounts,
} from "./holding-amounts";

const deriveBond = (v: Amounts, e: AmountField[]) =>
  deriveAmount(v, e, BOND_PRECISION);
const deriveMf = (v: Amounts, e: AmountField[]) =>
  deriveAmount(v, e, MF_PRECISION);

describe("deriveAmount (bond precision)", () => {
  it("derives price from quantity and total", () => {
    expect(
      deriveBond({ quantity: 3, price: null, total: 100000 }, [
        "quantity",
        "total",
      ]),
    ).toEqual({ field: "price", value: 33333.33 });
  });

  it("derives total from quantity and price", () => {
    expect(
      deriveBond({ quantity: 3, price: 333.33, total: null }, [
        "price",
        "quantity",
      ]),
    ).toEqual({ field: "total", value: 999.99 });
  });

  it("derives quantity from price and total, rounded to whole", () => {
    expect(
      deriveBond({ quantity: null, price: 1000, total: 10000 }, [
        "price",
        "total",
      ]),
    ).toEqual({ field: "quantity", value: 10 });
    expect(
      deriveBond({ quantity: null, price: 300, total: 1000 }, [
        "total",
        "price",
      ]),
    ).toEqual({ field: "quantity", value: 3 });
    expect(
      deriveBond({ quantity: null, price: 400, total: 1000 }, [
        "total",
        "price",
      ]),
    ).toEqual({ field: "quantity", value: 3 });
  });

  it("uses only the last two distinct edited fields", () => {
    expect(
      deriveBond({ quantity: 2, price: 10, total: 999 }, [
        "total",
        "quantity",
        "price",
      ]),
    ).toEqual({ field: "total", value: 20 });
  });

  it("returns null for missing, zero or invalid inputs", () => {
    const e: AmountField[] = ["quantity", "total"];
    expect(deriveBond({ quantity: null, price: null, total: 5 }, e)).toBeNull();
    expect(deriveBond({ quantity: 0, price: null, total: 5 }, e)).toBeNull();
    expect(deriveBond({ quantity: 2, price: null, total: NaN }, e)).toBeNull();
    expect(
      deriveBond({ quantity: 2, price: null, total: 5 }, ["quantity"]),
    ).toBeNull();
    expect(
      deriveBond({ quantity: null, price: 0, total: 5 }, ["price", "total"]),
    ).toBeNull();
    expect(
      deriveBond({ quantity: null, price: 1000, total: 10 }, ["price", "total"]),
    ).toBeNull();
  });
});

describe("deriveAmount (mutual fund precision)", () => {
  it("derives avg NAV at 4 dp from units and total", () => {
    expect(
      deriveMf({ quantity: 5385.28, price: null, total: 257470.24 }, [
        "quantity",
        "total",
      ]),
    ).toEqual({ field: "price", value: 47.81 });
    expect(
      deriveMf({ quantity: 3, price: null, total: 100 }, ["quantity", "total"]),
    ).toEqual({ field: "price", value: 33.3333 });
  });

  it("derives units at 3 dp from avg NAV and total", () => {
    expect(
      deriveMf({ quantity: null, price: 47.81, total: 257470.24 }, [
        "price",
        "total",
      ]),
    ).toEqual({ field: "quantity", value: 5385.28 });
    expect(
      deriveMf({ quantity: null, price: 30, total: 100 }, ["price", "total"]),
    ).toEqual({ field: "quantity", value: 3.333 });
  });

  it("derives total at 2 dp from units and avg NAV", () => {
    expect(
      deriveMf({ quantity: 5385.28, price: 47.81, total: null }, [
        "quantity",
        "price",
      ]),
    ).toEqual({ field: "total", value: 257470.24 });
  });
});

describe("bondAmountsConsistent", () => {
  it("passes at the tolerance edge", () => {
    // tolerance = 100 * 0.005 + 0.01 = 0.51
    expect(bondAmountsConsistent(100, 10, 1000)).toBe(true);
    expect(bondAmountsConsistent(100, 10, 1000.51)).toBe(true);
    expect(bondAmountsConsistent(100, 10, 999.49)).toBe(true);
  });

  it("fails just past the tolerance", () => {
    expect(bondAmountsConsistent(100, 10, 1000.52)).toBe(false);
    expect(bondAmountsConsistent(100, 10, 999.48)).toBe(false);
  });
});

describe("mfAmountsConsistent", () => {
  it("accepts units x avg NAV matching the total", () => {
    expect(mfAmountsConsistent(5385.28, 47.81, 257470.24)).toBe(true);
  });

  it("rejects a clearly different total", () => {
    expect(mfAmountsConsistent(5385.28, 47.81, 257480)).toBe(false);
  });
});
