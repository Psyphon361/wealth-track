import type { ReactNode } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import type { AssetType, HoldingMaster, HoldingRow } from "@/lib/types";
import type { gridFeatures } from "./features";

export type GridFeatures = typeof gridFeatures;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type GridColumn<TRow extends HoldingRow> = ColumnDef<GridFeatures, TRow, any>;

export interface RowHandlers<TRow> {
  onEdit: (row: TRow) => void;
  onDelete: (row: TRow) => void;
}

/** Multi-select filter; options and counts come from `facets[key]`. */
export interface FacetFilterDef {
  kind: "facet";
  key: string;
  title: string;
  /** Display labels for enum values; omitted for free-text facets. */
  labels?: Record<string, string>;
}

/** Numeric min/max filter shown in percent. */
export interface RangeFilterDef {
  kind: "range";
  title: string;
  minKey: string;
  maxKey: string;
}

/** Date from/to filter. */
export interface DateFilterDef {
  kind: "date";
  title: string;
  fromKey: string;
  toKey: string;
}

export type FilterDef = FacetFilterDef | RangeFilterDef | DateFilterDef;

/** A label/value pair on the details page; empty values render as a dash. */
export interface DetailField {
  label: string;
  value: string | null | undefined;
  /** Numeric value: rendered with the `num` utility. */
  figure?: boolean;
}

export interface DetailKpi {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
}

/** What the shared holding details page needs from each asset type. */
export interface DetailConfig<TRow extends HoldingRow> {
  subtitle: (item: TRow) => string | null;
  /** Fourth KPI card (Maturity / Price / NAV). */
  kpi: (item: TRow) => DetailKpi;
  /** Start and end dates for the tenure bar; omit for open-ended holdings. */
  tenure?: (item: TRow) => { start: string; end: string } | null;
  holding: (item: TRow) => DetailField[];
  instrument: (master: HoldingMaster, item: TRow) => DetailField[];
}

export interface GridConfig<TRow extends HoldingRow> {
  type: AssetType;
  /** Lower-case plural noun, e.g. "fixed deposits". */
  noun: string;
  searchPlaceholder: string;
  sortKeys: readonly string[];
  filters: FilterDef[];
  /** Labels for headers and the Columns menu, by column id. */
  columnLabels: Record<string, string>;
  createColumns: (handlers: RowHandlers<TRow>) => GridColumn<TRow>[];
  rowName: (row: TRow) => string;
  renderEditForm: (row: TRow, onSaved: () => void) => ReactNode;
  detail: DetailConfig<TRow>;
}

/** Every query-string key a filter definition reads or writes. */
export function filterParamKeys(filters: FilterDef[]): string[] {
  return filters.flatMap((f) =>
    f.kind === "facet"
      ? [f.key]
      : f.kind === "range"
        ? [f.minKey, f.maxKey]
        : [f.fromKey, f.toKey],
  );
}
