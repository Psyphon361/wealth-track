import { ASSET_CATALOG, ASSET_GROUPS } from "./asset-catalog";

export interface GroupRow {
  type: string;
  label: string;
  count: number;
  matured_count: number;
  invested: number;
  current: number;
  allocation_pct: number;
  gain: number | null;
  gain_pct: number | null;
  gain_base: number;
  day_change: number | null;
}

export interface GroupSubtotal {
  count: number;
  invested: number;
  current: number;
  allocation_pct: number;
  gain: number | null;
  gain_pct: number | null;
  day_change: number | null;
}

export interface RowGroup<T extends GroupRow = GroupRow> {
  name: string;
  rows: T[];
  subtotal: GroupSubtotal;
  showSubtotal: boolean;
}

function sumNonNull(values: (number | null)[]): number | null {
  const present = values.filter((v): v is number => v !== null);
  return present.length === 0 ? null : present.reduce((s, v) => s + v, 0);
}

function subtotal(rows: GroupRow[]): GroupSubtotal {
  const gain = sumNonNull(rows.map((r) => r.gain));
  const base = rows.reduce((s, r) => s + r.gain_base, 0);
  return {
    count: rows.reduce((s, r) => s + r.count, 0),
    invested: rows.reduce((s, r) => s + r.invested, 0),
    current: rows.reduce((s, r) => s + r.current, 0),
    allocation_pct: rows.reduce((s, r) => s + r.allocation_pct, 0),
    gain,
    gain_pct: gain !== null && base > 0 ? (gain / base) * 100 : null,
    day_change: sumNonNull(rows.map((r) => r.day_change)),
  };
}

export function groupRows<T extends GroupRow>(byType: T[]): RowGroup<T>[] {
  const visible = byType.filter((r) => r.count > 0 || r.matured_count > 0);
  const order = new Map(ASSET_CATALOG.map((a, i) => [a.type as string, i]));
  const groups: RowGroup<T>[] = [];
  for (const name of ASSET_GROUPS) {
    const types = new Set<string>(
      ASSET_CATALOG.filter((a) => a.group === name).map((a) => a.type),
    );
    const rows = visible
      .filter((r) => types.has(r.type))
      .sort((a, b) => (order.get(a.type) ?? 0) - (order.get(b.type) ?? 0));
    if (rows.length === 0) continue;
    groups.push({ name, rows, subtotal: subtotal(rows), showSubtotal: true });
  }
  if (groups.length === 1) groups[0].showSubtotal = false;
  return groups;
}
