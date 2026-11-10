import { canEdit, type EditGuardRow } from "./edit-guards";
import { formatDate, formatINR } from "./format";
import type { AssetType } from "./types";

/** Types with a quick-refresh action (POST /api/assets/{type}/{id}/update-value). */
export type UpdateValueType = "cash" | "pf" | "other" | "nps";

export const STALE_LINE = "Not updated for over 6 months";

const LABELS: Record<UpdateValueType, string> = {
  cash: "Update Balance",
  pf: "Update Balance",
  other: "Update Value",
  nps: "Update Units",
};

export function isUpdateValueType(type: AssetType): type is UpdateValueType {
  return type in LABELS;
}

/** Action label per type, or null for types without the action. */
export function updateValueLabel(type: AssetType): string | null {
  return isUpdateValueType(type) ? LABELS[type] : null;
}

/** The action shows for those four types, and never on a sold or settled holding. */
export function canUpdateValue(type: AssetType, row: EditGuardRow): boolean {
  return isUpdateValueType(type) && canEdit(row);
}

/** The parts of a holding the dialog reads. */
export interface UpdateValueRow {
  balance?: number;
  balance_date?: string;
  current_value?: number;
  value_date?: string;
  units?: number;
  contributed?: number;
}

export interface AmountDefaults {
  amount: string;
  date: string;
}

export interface NpsDefaults {
  units: string;
  contributed: string;
}

/** Pre-filled values of the balance/value form; the date is today. */
export function amountDefaults(
  type: "cash" | "pf" | "other",
  row: UpdateValueRow,
  today: string,
): AmountDefaults {
  const n = type === "other" ? row.current_value : row.balance;
  return { amount: n == null ? "" : String(n), date: today };
}

export function npsDefaults(row: UpdateValueRow): NpsDefaults {
  return {
    units: row.units == null ? "" : String(row.units),
    contributed: row.contributed == null ? "" : String(row.contributed),
  };
}

/** Request body per type (field names as the API expects them). */
export function amountBody(
  type: "cash" | "pf" | "other",
  amount: number,
  date: string,
): Record<string, number | string> {
  return type === "other"
    ? { current_value: amount, value_date: date }
    : { balance: amount, balance_date: date };
}

export function npsBody(units: number, contributed: number) {
  return { units, contributed };
}

/** Label of the amount field. */
export function amountLabel(type: "cash" | "pf" | "other"): string {
  return type === "other" ? "Current Value" : "Balance";
}

/** Helper text under the form: the current figure and its as-of date. */
export function currentFigureText(
  type: UpdateValueType,
  row: UpdateValueRow,
): string {
  if (type === "nps") {
    const units = (row.units ?? 0).toLocaleString("en-IN", {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    });
    return `Now ${units} units, ${formatINR(row.contributed ?? 0)} contributed`;
  }
  const amount = type === "other" ? row.current_value : row.balance;
  const date = type === "other" ? row.value_date : row.balance_date;
  const base = `Now ${formatINR(amount ?? 0)}`;
  return date ? `${base} as of ${formatDate(date)}` : base;
}
