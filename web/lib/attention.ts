import { formatDate, formatINR } from "./format";
import type { Attention } from "./types";

/** Rows shown per group before "Show All". */
export const ATTENTION_PREVIEW = 3;

/** Total items needing attention (the true counts, not the capped lists). */
export function attentionTotal(a: Attention): number {
  return a.counts.maturing + a.counts.stale + a.counts.sips;
}

/** The first few rows, or all returned rows when expanded. */
export function visibleRows<T>(rows: T[], expanded: boolean): T[] {
  return expanded ? rows : rows.slice(0, ATTENTION_PREVIEW);
}

/** Toggle label, or null when every row already fits: "Show All 5" / "Show Less". */
export function attentionToggleLabel(total: number, expanded: boolean): string | null {
  if (total <= ATTENTION_PREVIEW) return null;
  return expanded ? "Show Less" : `Show All ${total}`;
}

/** "Today", "Tomorrow" or "In 12 days". */
export function daysLeftText(days: number): string {
  if (days <= 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

/** "Matures 7 Jan 2027 · In 12 days". */
export function maturingLine(date: string, days: number): string {
  return `Matures ${formatDate(date)} · ${daysLeftText(days)}`;
}

/** "~₹1,00,000.00" when approximate, "—" when unknown. */
export function maturingAmountText(amount: number | null, approximate: boolean): string {
  if (amount == null) return "—";
  return `${approximate ? "~" : ""}${formatINR(amount)}`;
}

/** "7.25% p.a." or null. */
export function rateText(rate: number | null): string | null {
  return rate == null ? null : `${rate.toFixed(2)}% p.a.`;
}

/** "Last updated 7 Jan 2026". */
export function lastUpdatedText(asOf: string): string {
  return `Last updated ${formatDate(asOf)}`;
}

/** "Due 12 Nov 2026". */
export function dueText(date: string): string {
  return `Due ${formatDate(date)}`;
}

/** Details-page link of a holding. */
export function holdingHref(type: string, id: number): string {
  return `/portfolio/${type}/${id}`;
}

/** SIP fund link, or null when the SIP has no holding. */
export function sipHref(mutualFundId: number | null): string | null {
  return mutualFundId == null ? null : holdingHref("mf", mutualFundId);
}
