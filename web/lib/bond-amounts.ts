import { BOND_AMOUNT_MISMATCH_ERROR } from "../components/forms/schema";

export { BOND_AMOUNT_MISMATCH_ERROR };

export type BondAmountField = "quantity" | "price" | "total";

export interface BondAmounts {
  quantity: number | null;
  price: number | null;
  total: number | null;
}

export interface DerivedAmount {
  field: BondAmountField;
  value: number;
}

function valid(n: number | null): n is number {
  return n !== null && Number.isFinite(n) && n > 0;
}

function round2(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

/**
 * Derive the third amount from the two the user edited most recently.
 * `edited` lists field names, oldest first; the last two distinct ones are used.
 * Returns null when fewer than two fields are known or inputs are missing/invalid.
 */
export function deriveBondAmount(
  values: BondAmounts,
  edited: BondAmountField[],
): DerivedAmount | null {
  const pair = Array.from(new Set([...edited].reverse())).slice(0, 2);
  if (pair.length < 2) return null;
  const { quantity, price, total } = values;
  const has = (f: BondAmountField) => pair.includes(f);
  if (has("quantity") && has("total")) {
    if (!valid(quantity) || !valid(total)) return null;
    return { field: "price", value: round2(total / quantity) };
  }
  if (has("quantity") && has("price")) {
    if (!valid(quantity) || !valid(price)) return null;
    return { field: "total", value: round2(quantity * price) };
  }
  if (!valid(price) || !valid(total)) return null;
  const q = Math.round(total / price);
  return q > 0 ? { field: "quantity", value: q } : null;
}

/** Same tolerance as the API: |qty * price - total| <= qty * 0.005 + 0.01. */
export function bondAmountsConsistent(
  quantity: number,
  price: number,
  total: number,
): boolean {
  if (![quantity, price, total].every(Number.isFinite)) return true;
  return Math.abs(quantity * price - total) <= quantity * 0.005 + 0.01 + 1e-9;
}
