import { formatDate, formatINRWhole } from "./format";
import type { UnsettledItem } from "./types";

/** Rows shown before "Show All". */
export const UNSETTLED_PREVIEW = 3;

/** Card title: "2 matured holdings to settle · ₹3,10,000". */
export function unsettledTitle(count: number, amount: number): string {
  const noun = count === 1 ? "matured holding" : "matured holdings";
  return `${count} ${noun} to settle · ${formatINRWhole(amount)}`;
}

/** Row line: "Matured 7 Jan 2027". */
export function maturedOnText(iso: string): string {
  return `Matured ${formatDate(iso)}`;
}

/** The rows to list: the first few, or all of them when expanded. */
export function visibleUnsettled(
  items: UnsettledItem[],
  expanded: boolean,
): UnsettledItem[] {
  return expanded ? items : items.slice(0, UNSETTLED_PREVIEW);
}

/** Toggle label, or null when every row already fits: "Show All 5" / "Show Less". */
export function unsettledToggleLabel(
  total: number,
  expanded: boolean,
): string | null {
  if (total <= UNSETTLED_PREVIEW) return null;
  return expanded ? "Show Less" : `Show All ${total}`;
}

/** Details-page link that opens the settle dialog. */
export function settleHref(item: Pick<UnsettledItem, "type" | "id">): string {
  return `/portfolio/${item.type}/${item.id}?settle=1`;
}
