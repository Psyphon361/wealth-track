import { formatDate } from "@/lib/format";
import type { DetailKpi } from "@/components/portfolio/grid/types";

const DAY_MS = 86_400_000;

function toDay(iso: string): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return Date.UTC(y, m - 1, d) / DAY_MS;
}

function today(): number {
  const n = new Date();
  return Date.UTC(n.getFullYear(), n.getMonth(), n.getDate()) / DAY_MS;
}

/** Whole days from today to `iso` (negative once passed). */
export function daysUntil(iso: string): number {
  return toDay(iso) - today();
}

/** Percent of the start→end span elapsed today, clamped to 0–100. */
export function elapsedPct(start: string, end: string): number {
  const span = toDay(end) - toDay(start);
  if (span <= 0) return 100;
  const pct = ((today() - toDay(start)) / span) * 100;
  return Math.min(100, Math.max(0, pct));
}

export function formatTenure(y: number, m: number, d: number): string {
  const parts = [
    y ? `${y} ${y === 1 ? "year" : "years"}` : "",
    m ? `${m} ${m === 1 ? "month" : "months"}` : "",
    d ? `${d} ${d === 1 ? "day" : "days"}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" ") : "0 days";
}

/** Maturity KPI shared by fd, rd and bond. */
export function maturityKpi(
  date: string | undefined,
  matured: boolean,
): DetailKpi {
  if (!date) return { label: "Maturity", value: "—" };
  const days = daysUntil(date);
  return {
    label: "Maturity",
    value: <span className="num">{formatDate(date)}</span>,
    sub: matured || days <= 0 ? "Matured" : `${days} ${days === 1 ? "day" : "days"} left`,
  };
}
