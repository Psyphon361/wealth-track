import { describe, expect, it } from "vitest";
import { bondAmountsConsistent, deriveBondAmount } from "./bond-amounts";

describe("deriveBondAmount", () => {
  it("derives price from quantity and total", () => {
    expect(
      deriveBondAmount({ quantity: 3, price: null, total: 100000 }, [
        "quantity",
        "total",
      ]),
    ).toEqual({ field: "price", value: 33333.33 });
  });

  it("derives total from quantity and price", () => {
    expect(
      deriveBondAmount({ quantity: 3, price: 333.33, total: null }, [
        "price",
        "quantity",
      ]),
    ).toEqual({ field: "total", value: 999.99 });
  });

  it("derives quantity from price and total, rounded to whole", () => {
    expect(
      deriveBondAmount({ quantity: null, price: 1000, total: 10000 }, [
        "price",
        "total",
      ]),
    ).toEqual({ field: "quantity", value: 10 });
    expect(
      deriveBondAmount({ quantity: null, price: 300, total: 1000 }, [
        "total",
        "price",
      ]),
    ).toEqual({ field: "quantity", value: 3 });
    expect(
      deriveBondAmount({ quantity: null, price: 400, total: 1000 }, [
        "total",
        "price",
      ]),
    ).toEqual({ field: "quantity", value: 3 });
  });

  it("uses only the last two distinct edited fields", () => {
    expect(
      deriveBondAmount({ quantity: 2, price: 10, total: 999 }, [
        "total",
        "quantity",
        "price",
      ]),
    ).toEqual({ field: "total", value: 20 });
  });

  it("returns null for missing, zero or invalid inputs", () => {
    const e: ("quantity" | "total")[] = ["quantity", "total"];
    expect(deriveBondAmount({ quantity: null, price: null, total: 5 }, e)).toBeNull();
    expect(deriveBondAmount({ quantity: 0, price: null, total: 5 }, e)).toBeNull();
    expect(deriveBondAmount({ quantity: 2, price: null, total: NaN }, e)).toBeNull();
    expect(
      deriveBondAmount({ quantity: 2, price: null, total: 5 }, ["quantity"]),
    ).toBeNull();
    expect(
      deriveBondAmount({ quantity: null, price: 0, total: 5 }, ["price", "total"]),
    ).toBeNull();
    expect(
      deriveBondAmount({ quantity: null, price: 1000, total: 10 }, ["price", "total"]),
    ).toBeNull();
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
