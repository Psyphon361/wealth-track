import { formatINRWhole } from "./format";
import type {
  BenchmarkPair,
  ReferenceRate,
  ReturnGroup,
  ReturnsBenchmark,
  ReturnsExcluded,
} from "./types";

export interface ReturnBar {
  /** left edge and width, percent of the track; the zero line sits at `zero` */
  left: number;
  width: number;
  zero: number;
}

/**
 * Bars for signed values sharing one axis that always includes zero. Returns null entries
 * for null values.
 */
export function returnBars(values: (number | null)[]): (ReturnBar | null)[] {
  const nums = values.filter((v): v is number => v !== null);
  const hi = Math.max(0, ...nums);
  const lo = Math.min(0, ...nums);
  const span = hi - lo;
  if (span === 0) return values.map((v) => (v === null ? null : { left: 0, width: 0, zero: 0 }));
  const zero = lo === 0 ? 0 : (-lo / span) * 100;
  return values.map((v) => {
    if (v === null) return null;
    const w = (Math.abs(v) / span) * 100;
    return { left: v >= 0 ? zero : zero - w, width: w, zero };
  });
}

export function signOf(n: number): string {
  return n > 0 ? "+" : n < 0 ? "−" : "";
}

/** "12.4%" with one decimal, no sign. */
export function pct1(n: number): string {
  return `${n.toFixed(1)}%`;
}

/** "+12.4%" / "−3.1%". */
export function signedPct1(n: number): string {
  return `${signOf(n)}${Math.abs(n).toFixed(1)}%`;
}

/** "+₹57,000" / "−₹57,000". */
export function signedWhole(n: number): string {
  return `${signOf(n)}${formatINRWhole(Math.abs(n))}`;
}

/** Big figure and its small suffix: "12.4%" + "a year" (annualised) or "in under a year". */
export function overallHeadline(g: ReturnGroup): { value: string; suffix: string } | null {
  if (g.return_pct === null) return null;
  return {
    value: pct1(g.return_pct),
    suffix: g.annualised ? "a year" : "in under a year",
  };
}

export function overallSentence(g: ReturnGroup): string {
  const amount = formatINRWhole(Math.abs(g.gain));
  const outcome = g.gain < 0 ? `a loss of ${amount}` : `a gain of ${amount}`;
  return `${formatINRWhole(g.invested)} invested is now worth ${formatINRWhole(g.current)}, ${outcome}.`;
}

/** "Since Mar 2024" from an ISO date. */
export function sinceLabel(iso: string): string {
  const [y, m] = iso.slice(0, 10).split("-").map(Number);
  const month = new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-GB", {
    month: "short",
    timeZone: "UTC",
  });
  return `Since ${month} ${y}`;
}

/** Hover detail for one group row: "Gain ₹57,000 on ₹4,53,000 invested". */
export function groupDetail(g: ReturnGroup): string {
  const word = g.gain < 0 ? "Loss" : "Gain";
  return `${word} ${formatINRWhole(Math.abs(g.gain))} on ${formatINRWhole(g.invested)} invested`;
}

export interface CompareRow {
  key: "you" | "nifty" | "fd" | "inflation";
  label: string;
  note?: string;
  value: number;
}

function pairOf(b: ReturnsBenchmark): { pair: BenchmarkPair; equity: boolean } | null {
  if (b.equity && b.equity.your_pct !== null && b.equity.benchmark_pct !== null) {
    return { pair: b.equity, equity: true };
  }
  if (b.overall && b.overall.your_pct !== null && b.overall.benchmark_pct !== null) {
    return { pair: b.overall, equity: false };
  }
  return null;
}

/** One-sentence comparison, or null when there is nothing to compare. */
export function compareSentence(b: ReturnsBenchmark | null): string | null {
  if (!b) return null;
  const p = pairOf(b);
  if (!p || p.pair.your_pct === null || p.pair.benchmark_pct === null) return null;
  const per = p.pair.annualised ? " a year" : " in under a year";
  return `Your ${p.equity ? "equity" : "money"} earned ${pct1(p.pair.your_pct)}${per}. A ${b.label} on the same dates earned ${pct1(p.pair.benchmark_pct)}.`;
}

/** Up to four rows; null values are omitted. */
export function compareRows(b: ReturnsBenchmark | null): CompareRow[] {
  if (!b) return [];
  const p = pairOf(b);
  const rows: CompareRow[] = [];
  if (p && p.pair.your_pct !== null && p.pair.benchmark_pct !== null) {
    rows.push(
      { key: "you", label: "You", value: p.pair.your_pct },
      { key: "nifty", label: b.label, value: p.pair.benchmark_pct },
    );
  }
  if (b.fd_rate !== null) rows.push({ key: "fd", label: "Your FDs", value: b.fd_rate });
  if (b.inflation_pct !== null) {
    rows.push({
      key: "inflation",
      label: "Inflation",
      note: b.inflation_period ?? undefined,
      value: b.inflation_pct,
    });
  }
  return rows;
}

/** Footnote under the comparison bars. */
export function compareFootnote(
  b: ReturnsBenchmark,
  formatDate: (iso: string) => string,
): string {
  const nav = b.nav_date ? ` (NAV as of ${formatDate(b.nav_date)})` : "";
  return `Nifty figure replays your own investment dates into ${b.scheme_name}${nav}.`;
}

function holdingsCount(n: number): string {
  return n === 1 ? "1 holding" : `${n} holdings`;
}

/** "Not in returns: 3 holdings with no dated investments (…) and 1 Other holding …." or null. */
export function excludedText(e: ReturnsExcluded): string | null {
  const parts: string[] = [];
  if (e.no_flows > 0) {
    parts.push(`${holdingsCount(e.no_flows)} with no dated investments (cash, EPF/PPF, NPS)`);
  }
  if (e.at_cost > 0) parts.push(`${holdingsCount(e.at_cost)} valued at cost`);
  if (e.other_without_invested > 0) {
    parts.push(`${e.other_without_invested} Other ${e.other_without_invested === 1 ? "holding" : "holdings"} without an amount invested`);
  }
  if (parts.length === 0) return null;
  const body =
    parts.length === 1
      ? parts[0]
      : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;
  return `Not in returns: ${body}.`;
}

/** "EPF 8.25% · PPF 7.1% · NPS (Scheme) 11.2% a year"; null rates omitted. */
export function ratesText(rates: ReferenceRate[]): string | null {
  const parts = rates
    .filter((r) => r.rate_pct !== null)
    .map((r) => `${r.type === "nps" ? `NPS (${r.name})` : r.name} ${parseFloat((r.rate_pct as number).toFixed(2))}%`);
  return parts.length === 0 ? null : `${parts.join(" · ")} a year`;
}
