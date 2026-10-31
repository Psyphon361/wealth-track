import type { NetWorthRange } from "./types";

export const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function parts(iso: string): [number, number, number] {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return [y, m, d];
}

/** "23 Sep 2026" with a fixed month array (never "Sept"). */
export function formatDateShortMonth(iso: string): string {
  const [y, m, d] = parts(iso);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** YYYY-MM-DD -> "12 Mar" (1M) or "Mar 26" (other ranges). */
export function tickLabel(iso: string, range: NetWorthRange): string {
  const [y, m, d] = parts(iso);
  if (range === "1m") return `${d} ${MONTHS[m - 1]}`;
  return `${MONTHS[m - 1]} ${String(y).slice(2)}`;
}

/**
 * Explicit x ticks: first point date of each month (6M/1Y), widened to
 * quarters/years for long All ranges so there are at most ~8. Undefined for 1M.
 */
export function pickTicks(dates: string[], range: NetWorthRange): string[] | undefined {
  if (range === "1m" || dates.length === 0) return undefined;
  const firstOf = (keyOf: (y: number, m: number) => string): string[] => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const iso of dates) {
      const [y, m] = parts(iso);
      const k = keyOf(y, m);
      if (!seen.has(k)) {
        seen.add(k);
        out.push(iso);
      }
    }
    return out;
  };
  const monthly = firstOf((y, m) => `${y}-${m}`);
  let ticks = monthly;
  if (range === "all") {
    const [y0] = parts(dates[0]);
    const [y1] = parts(dates[dates.length - 1]);
    if (y1 - y0 > 2) ticks = firstOf((y, m) => `${y}-${Math.floor((m - 1) / 3)}`);
    if (ticks.length > 8) ticks = firstOf((y) => `${y}`);
  }
  // Thin evenly if still too many (e.g. 1Y monthly = 12-13).
  if (ticks.length > 8) {
    const step = Math.ceil(ticks.length / 8);
    ticks = ticks.filter((_, i) => i % step === 0);
  }
  return ticks;
}
