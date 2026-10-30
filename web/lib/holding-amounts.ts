export type AmountField = "quantity" | "price" | "total";

export interface Amounts {
  quantity: number | null;
  price: number | null;
  total: number | null;
}

export interface DerivedAmount {
  field: AmountField;
  value: number;
}

/** Decimal places kept for each of the three amounts. */
export interface AmountPrecision {
  quantity: number;
  price: number;
  total: number;
}

export const BOND_PRECISION: AmountPrecision = { quantity: 0, price: 2, total: 2 };
export const MF_PRECISION: AmountPrecision = { quantity: 3, price: 4, total: 2 };

function valid(n: number | null): n is number {
  return n !== null && Number.isFinite(n) && n > 0;
}

function roundTo(n: number, dp: number): number {
  const f = 10 ** dp;
  return Math.round((n + Number.EPSILON) * f) / f;
}

/**
 * Derive the third amount from the two the user edited most recently.
 * `edited` lists field names, oldest first; the last two distinct ones are used.
 * Returns null when fewer than two fields are known or inputs are missing/invalid.
 */
export function deriveAmount(
  values: Amounts,
  edited: AmountField[],
  precision: AmountPrecision,
): DerivedAmount | null {
  const pair = Array.from(new Set([...edited].reverse())).slice(0, 2);
  if (pair.length < 2) return null;
  const { quantity, price, total } = values;
  const has = (f: AmountField) => pair.includes(f);
  if (has("quantity") && has("total")) {
    if (!valid(quantity) || !valid(total)) return null;
    return { field: "price", value: roundTo(total / quantity, precision.price) };
  }
  if (has("quantity") && has("price")) {
    if (!valid(quantity) || !valid(price)) return null;
    return { field: "total", value: roundTo(quantity * price, precision.total) };
  }
  if (!valid(price) || !valid(total)) return null;
  const q = roundTo(total / price, precision.quantity);
  return q > 0 ? { field: "quantity", value: q } : null;
}

/** Bond, same tolerance as the API: |qty * price - total| <= qty * 0.005 + 0.01. */
export function bondAmountsConsistent(
  quantity: number,
  price: number,
  total: number,
): boolean {
  if (![quantity, price, total].every(Number.isFinite)) return true;
  return Math.abs(quantity * price - total) <= quantity * 0.005 + 0.01 + 1e-9;
}

/**
 * Mutual fund, same tolerance as the API:
 * |units * nav - total| <= units * 0.00005 + nav * 0.0005 + 0.01.
 */
export function mfAmountsConsistent(
  units: number,
  avgNav: number,
  total: number,
): boolean {
  if (![units, avgNav, total].every(Number.isFinite)) return true;
  return (
    Math.abs(units * avgNav - total) <=
    units * 0.00005 + avgNav * 0.0005 + 0.01 + 1e-9
  );
}
