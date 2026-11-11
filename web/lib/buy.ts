import { z } from "zod";
import {
  MAX_MONEY,
  SELL_DATE_BEFORE_PURCHASE_ERROR,
  exitDate,
  isValidISODate,
  moneyNumber,
  positiveUnits,
  salePrice,
} from "@/components/forms/schema";
import { isClosed, type EditGuardRow } from "./edit-guards";
import type { AssetType } from "./types";

// ---- Buy More rules (same wording as api/app/schemas/buys.py) ----

export const BUY_DATE_BEFORE_LAST_SALE_ERROR = "Date can't be before the last sale";

export const BUY_INFO_LINE =
  "Bought with money from one of your accounts? Update that account's balance yourself, so it isn't counted twice.";
export const BUY_UNITS_HINT =
  "Leave blank to use amount ÷ NAV. Enter the units from your statement if they differ.";

export const UNDO_BUY_TITLE = "Undo this buy?";
export const UNDO_BUY_KEEP = "Keep It";
export const UNDO_BUY_CONFIRM = "Undo";
export const UNDO_BUY_PENDING = "Undoing…";

/** Only an open mutual fund can be added to (partly sold is fine). */
export function canBuy(type: AssetType, row: EditGuardRow): boolean {
  return type === "mf" && !isClosed(row);
}

/** Amount invested: > 0, at most 2 decimals, at most ₹100 crore. */
export const buyAmount = moneyNumber.refine(
  (n) => Math.abs(n * 100 - Math.round(n * 100)) < 1e-6,
  "Up to 2 decimal places allowed",
);

/** NAV per unit: > 0, at most 4 decimals, at most ₹100 crore. */
export const buyNav = salePrice;

/** Units from a statement: blank is undefined, else the usual unit rules (3 decimals). */
export const buyUnits = z
  .string()
  .trim()
  .transform((v, ctx): number | undefined => {
    if (v === "") return undefined;
    const r = positiveUnits.safeParse(v);
    if (!r.success) {
      for (const i of r.error.issues) ctx.addIssue({ code: "custom", message: i.message });
      return z.NEVER;
    }
    return r.data;
  });

/** Date of a buy: on or after 1 Jan 1990 and not in the future. */
export const buyDate = exitDate;

/** Dates a buy can't have: before the purchase date or before the last sale. Null when fine. */
export function buyDateError(
  date: string,
  purchaseDate: string | null,
  lastSale: string | null,
): string | null {
  if (!isValidISODate(date)) return null;
  if (purchaseDate && date < purchaseDate) return SELL_DATE_BEFORE_PURCHASE_ERROR;
  if (lastSale && date < lastSale) return BUY_DATE_BEFORE_LAST_SALE_ERROR;
  return null;
}

/** Date of the holding's latest sale, or null. */
export function lastSaleDate(row: {
  exit?: { kind: string; date?: string } | null;
}): string | null {
  const exit = row.exit;
  return exit && exit.kind === "sale" && exit.date ? exit.date : null;
}

/** Units a buy adds: the entered units, else amount ÷ NAV to 3 decimals; null until both are known. */
export function previewUnits(
  amount: number | null,
  nav: number | null,
  units: number | null,
): number | null {
  if (units !== null) return units > 0 ? units : null;
  if (amount === null || nav === null || amount <= 0 || nav <= 0) return null;
  if (amount > MAX_MONEY) return null;
  return Math.round((amount / nav + Number.EPSILON) * 1000) / 1000;
}

export interface BuyBody {
  date: string;
  amount: number;
  nav: number;
  units?: number;
}

/** Request body: units are left out when blank. */
export function buyBody(v: {
  date: string;
  amount: number;
  nav: number;
  units: number | undefined;
}): BuyBody {
  const body: BuyBody = { date: v.date, amount: v.amount, nav: v.nav };
  if (v.units !== undefined) body.units = v.units;
  return body;
}

export interface BuyResult {
  message: string;
  description?: string;
  transaction_id: number;
  units_added: number;
  units: number;
  invested_amount: number;
  avg_nav: number;
}

export function buyPath(id: number): string {
  return `/holdings/mf/${id}/buy`;
}

export function undoBuyPath(id: number, txnId: number): string {
  return `/holdings/mf/${id}/buys/${txnId}`;
}
