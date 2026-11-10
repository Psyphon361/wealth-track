/** Header hint for the XIRR column (the API gives null under a year of history). */
export const XIRR_HINT = "Needs at least a year of history";

/** The XIRR figure to show on the details page, or null to hide the tile. */
export function xirrKpi(
  item: object,
  startDate?: string | null,
): { value: number; startDate: string | null } | null {
  const v = (item as { xirr?: number | null }).xirr;
  if (v == null || !Number.isFinite(v)) return null;
  return { value: v, startDate: startDate || null };
}

/** The date a holding's returns start from, when the item carries one. */
export function xirrStartDate(item: object): string | null {
  const r = item as { start_date?: unknown; purchase_date?: unknown; buy_date?: unknown };
  for (const d of [r.start_date, r.purchase_date, r.buy_date]) {
    if (typeof d === "string" && d) return d;
  }
  return null;
}
