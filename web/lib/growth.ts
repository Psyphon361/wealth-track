import { formatINRWhole } from "./format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Colour of "Your money" in the split bar, legends and month columns. */
export const MONEY_COLOR = "oklch(0.68 0.13 265)";

/** "2026-11" -> "Nov 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return `${MONTHS[m - 1] ?? month} ${y}`;
}

/** "+" / "-" / "" sign prefix helper. */
export function signOf(n: number): "+" | "-" | "" {
  return n > 0 ? "+" : n < 0 ? "-" : "";
}

/** Signed whole-rupee text: "+₹2,60,970". Amounts that round to zero carry no sign. */
export function signedWhole(n: number): string {
  const r = Math.round(n);
  return `${signOf(r)}${formatINRWhole(Math.abs(r))}`;
}

/** "You put in X" / "You took out X" / "" for the new-money part. */
function moneyPhrase(newMoney: number): string {
  const r = Math.round(newMoney);
  if (r > 0) return `put in ${formatINRWhole(r)}`;
  if (r < 0) return `took out ${formatINRWhole(-r)}`;
  return "";
}

/** "your investments grew X" / "fell X" / "" for the growth part. */
function growthPhrase(growth: number): string {
  const r = Math.round(growth);
  if (r > 0) return `investments grew ${formatINRWhole(r)}`;
  if (r < 0) return `investments fell ${formatINRWhole(-r)}`;
  return "";
}

/** One plain sentence explaining a period's change. */
export function changeSentence(newMoney: number, growth: number): string {
  const m = moneyPhrase(newMoney);
  const g = growthPhrase(growth);
  if (!m && !g) return "No change in this period.";
  if (!m) return `Your ${g}.`;
  if (!g) return `You ${m}.`;
  return `You ${m} and your ${g}.`;
}

/** Shares (percent, summing to 100) of |new money| and |growth| in the change; 0/0 when both are 0. */
export function splitShares(newMoney: number, growth: number): { money: number; growth: number } {
  const a = Math.abs(newMoney);
  const b = Math.abs(growth);
  const total = a + b;
  if (total <= 0) return { money: 0, growth: 0 };
  return { money: (a / total) * 100, growth: (b / total) * 100 };
}

function parts(iso: string): { y: number; m: number; d: number } {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return { y, m, d };
}

/** "31 Oct – 3 Nov"; the year is added to both ends only when the years differ. */
export function dateRangeLabel(startIso: string, endIso: string): string {
  const s = parts(startIso);
  const e = parts(endIso);
  const fmt = (p: { y: number; m: number; d: number }, withYear: boolean) =>
    `${p.d} ${MONTHS[p.m - 1]}${withYear ? ` ${p.y}` : ""}`;
  const withYear = s.y !== e.y;
  return `${fmt(s, withYear)} – ${fmt(e, withYear)}`;
}

/** Short column label: month name, plus the year on January and on the first column. */
export function columnLabel(month: string, first: boolean): { month: string; year: number | null } {
  const [y, m] = month.split("-").map(Number);
  return { month: MONTHS[m - 1] ?? month, year: first || m === 1 ? y : null };
}

export interface ColumnSegment {
  kind: "money" | "growth";
  value: number;
  /** distance from the chart bottom and height, percent of the chart height */
  bottom: number;
  height: number;
}

export interface MonthColumn {
  month: string;
  segments: ColumnSegment[];
}

/**
 * Column geometry for the month chart. Each column stacks new money then growth away from a zero
 * baseline (positives up, negatives down). Heights are percent of the chart height; `zero` is the
 * baseline's distance from the bottom. Non-zero segments get a small minimum height.
 */
export function monthColumns(
  months: { month: string; new_money: number; growth: number }[],
): { columns: MonthColumn[]; zero: number } {
  const sorted = [...months].sort((a, b) => a.month.localeCompare(b.month));
  let up = 0;
  let down = 0;
  for (const m of sorted) {
    let u = 0;
    let d = 0;
    for (const v of [m.new_money, m.growth]) {
      if (v > 0) u += v;
      else d += -v;
    }
    up = Math.max(up, u);
    down = Math.max(down, d);
  }
  const total = up + down;
  const zero = total > 0 ? (down / total) * 100 : 0;
  const MIN = 1.5;
  const columns = sorted.map((m) => {
    let posTop = zero;
    let negBottom = zero;
    const segments: ColumnSegment[] = [];
    const items: [ColumnSegment["kind"], number][] = [
      ["money", m.new_money],
      ["growth", m.growth],
    ];
    for (const [kind, value] of items) {
      if (value === 0 || total <= 0) {
        segments.push({ kind, value, bottom: zero, height: 0 });
        continue;
      }
      const h = Math.max(MIN, (Math.abs(value) / total) * 100);
      if (value > 0) {
        segments.push({ kind, value, bottom: posTop, height: h });
        posTop += h;
      } else {
        negBottom -= h;
        segments.push({ kind, value, bottom: negBottom, height: h });
      }
    }
    return { month: m.month, segments };
  });
  return { columns, zero };
}
