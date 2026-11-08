import type { CasPreviewRow } from "@/lib/types";

export type CasRowAction = "update" | "create";

export const SALES_BADGE = "Has sales recorded here";
export const SALES_HELPER =
  "Sales are recorded for this fund here, so it can't be updated from a statement.";

/** A single match that has sales recorded: it can only be added as new, never updated. */
export function updateBlocked(r: CasPreviewRow): boolean {
  return r.existing.length === 1 && r.existing[0].has_sales;
}

/** The action a row will use: add as new unless exactly one holding matches and may be updated. */
export function rowAction(
  r: CasPreviewRow,
  chosen?: CasRowAction,
): CasRowAction {
  if (r.existing.length !== 1 || updateBlocked(r)) return "create";
  return chosen ?? "update";
}

/** Rows ticked at first: every importable row, except those that can't be updated (default is skip). */
export function defaultSelected(rows: CasPreviewRow[]): Set<string> {
  return new Set(
    rows.filter((r) => r.importable && !updateBlocked(r)).map((r) => r.key),
  );
}
