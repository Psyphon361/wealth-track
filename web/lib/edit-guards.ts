import type { AssetType } from "./types";

/** Fields locked when a holding is sold in part (mirrors api/app/schemas/assets.py). */
export const SOLD_IN_PART_FIELDS: Readonly<Record<string, readonly string[]>> = {
  stock: ["quantity", "avg_buy_price", "buy_date"],
  bond: ["quantity", "purchase_price", "invested_amount", "purchase_date"],
  mf: ["units", "avg_nav", "invested_amount", "purchase_date"],
  gold: ["weight_grams", "invested_amount", "purchase_date"],
  other: ["invested_amount", "acquired_on"],
};

/** The parts of a valued holding the edit rules look at. */
export interface EditGuardRow {
  status: "active" | "matured" | "sold";
  settled?: boolean;
  closed_on?: string | null;
  exit?: { kind: "maturity" | "sale" } | null;
}

/** Sold in full or settled: the API refuses edits until the exit is undone. */
export function isClosed(row: EditGuardRow): boolean {
  return row.status === "sold" || !!row.closed_on || !!row.settled;
}

/** A sale exists but some is still held. */
export function isSoldInPart(row: EditGuardRow): boolean {
  return !isClosed(row) && row.exit?.kind === "sale";
}

/** Closed holdings can't be edited (matured but unsettled ones can). */
export function canEdit(row: EditGuardRow): boolean {
  return !isClosed(row);
}

/** Form fields locked in the Edit dialog (none unless the holding is sold in part). */
export function readOnlyFields(
  type: AssetType,
  row: EditGuardRow,
): readonly string[] {
  return isSoldInPart(row) ? (SOLD_IN_PART_FIELDS[type] ?? []) : [];
}
