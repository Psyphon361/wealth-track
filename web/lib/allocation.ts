export interface AllocationInput {
  type: string;
  label: string;
  current: number;
  allocation_pct: number;
}

export interface AllocationSlice {
  /** Asset slug, or "more" for the folded slice. */
  key: string;
  label: string;
  value: number;
  pct: number;
  /** Number of types folded into a "More" slice. */
  folded?: number;
}

const MAX_SLICES = 5;

/** Types with value, largest first: the top 5 plus "More" when more than 6 exist. */
export function allocationSlices(byType: AllocationInput[]): AllocationSlice[] {
  const sorted = byType
    .filter((r) => r.current > 0)
    .sort((a, b) => b.current - a.current)
    .map((r) => ({
      key: r.type,
      label: r.label,
      value: r.current,
      pct: r.allocation_pct,
    }));
  if (sorted.length <= MAX_SLICES + 1) return sorted;
  const rest = sorted.slice(MAX_SLICES);
  return [
    ...sorted.slice(0, MAX_SLICES),
    {
      key: "more",
      label: "More",
      value: rest.reduce((s, r) => s + r.value, 0),
      pct: rest.reduce((s, r) => s + r.pct, 0),
      folded: rest.length,
    },
  ];
}
