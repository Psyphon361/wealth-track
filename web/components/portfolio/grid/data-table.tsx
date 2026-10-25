"use client";

import { useEffect, useMemo, useState } from "react";
import {
  functionalUpdate,
  useTable,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
} from "@tanstack/react-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { HoldingRow, HoldingsResponse, SortDir } from "@/lib/types";
import { sortAria } from "./column-header";
import { RIGHT_ALIGNED } from "./configs/shared";
import { gridFeatures } from "./features";
import { Pagination } from "./pagination";
import { Toolbar } from "./toolbar";
import type { GridConfig } from "./types";
import {
  DEFAULT_DIR,
  DEFAULT_SORT,
  hasActiveFilters,
  type FilterPatch,
  type HoldingsFilters,
} from "./use-holdings-query";

const storageKey = (type: string) => `wt.portfolio.columns.${type}`;

/** Saved visibility, limited to known, hideable columns (new columns stay visible). */
function readVisibility(
  type: string,
  hideable: ReadonlySet<string>,
): ColumnVisibilityState {
  try {
    const raw = window.localStorage.getItem(storageKey(type));
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {};
    }
    const out: ColumnVisibilityState = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (typeof v === "boolean" && hideable.has(k)) out[k] = v;
    }
    return out;
  } catch {
    return {};
  }
}

function sameVisibility(a: ColumnVisibilityState, b: ColumnVisibilityState) {
  const ka = Object.keys(a);
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k]);
}

function writeVisibility(type: string, v: ColumnVisibilityState) {
  try {
    window.localStorage.setItem(storageKey(type), JSON.stringify(v));
  } catch {
    // storage unavailable; visibility just won't persist
  }
}

export function TableSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading…">
      <div className="flex flex-wrap gap-2">
        <Skeleton className="h-8 w-full sm:w-64" />
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-8 w-20" />
        <Skeleton className="h-8 w-20" />
      </div>
      <div className="rounded-xl border">
        <Skeleton className="h-9 rounded-b-none" />
        {Array.from({ length: 8 }, (_, i) => (
          <div key={i} className="border-t p-2">
            <Skeleton className="h-8" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function HoldingsGrid<TRow extends HoldingRow>({
  config,
  data,
  filters,
  fetching,
  onFilters,
  onReset,
  onSort,
  onPage,
  onEdit,
  onDelete,
}: {
  config: GridConfig<TRow>;
  data: HoldingsResponse<TRow>;
  filters: HoldingsFilters;
  fetching: boolean;
  onFilters: (patch: FilterPatch) => void;
  onReset: () => void;
  onSort: (sort: string, dir: SortDir) => void;
  onPage: (page: number) => void;
  onEdit: (row: TRow) => void;
  onDelete: (row: TRow) => void;
}) {
  const [visibility, setVisibility] = useState<ColumnVisibilityState>({});
  const columns = useMemo(
    () => config.createColumns({ onEdit, onDelete }),
    [config, onEdit, onDelete],
  );

  // Apply the saved value after mount (avoids an SSR hydration mismatch).
  useEffect(() => {
    const hideable = new Set<string>();
    for (const col of columns) {
      const id = col.id;
      if (id && col.enableHiding !== false) hideable.add(id);
    }
    const saved = readVisibility(config.type, hideable);
    // Never replace state with a new-but-equal object.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVisibility((prev) => (sameVisibility(prev, saved) ? prev : saved));
  }, [config.type, columns]);

  const sorting = useMemo<SortingState>(
    () => [{ id: filters.sort, desc: filters.dir === "desc" }],
    [filters.sort, filters.dir],
  );
  const pagination = useMemo<PaginationState>(
    () => ({ pageIndex: filters.page - 1, pageSize: data.page_size }),
    [filters.page, data.page_size],
  );
  const state = useMemo(
    () => ({ sorting, pagination, columnVisibility: visibility }),
    [sorting, pagination, visibility],
  );

  const table = useTable({
    features: gridFeatures,
    columns,
    data: data.items,
    getRowId: (row) => String(row.id),
    manualSorting: true,
    manualFiltering: true,
    manualPagination: true,
    rowCount: data.total,
    state,
    onSortingChange: (updater) => {
      const next = functionalUpdate(updater, sorting)[0];
      if (next) onSort(next.id, next.desc ? "desc" : "asc");
      else onSort(DEFAULT_SORT, DEFAULT_DIR);
    },
    onPaginationChange: (updater) => {
      const next = functionalUpdate(updater, pagination);
      onPage(next.pageIndex + 1);
    },
    onColumnVisibilityChange: (updater) => {
      const next = functionalUpdate(updater, visibility);
      setVisibility(next);
      writeVisibility(config.type, next);
    },
  });

  const rows = table.getRowModel().rows;
  const hasFilters = hasActiveFilters(filters);
  const visibleCount = table.getVisibleLeafColumns().length;

  return (
    <div className="min-w-0 space-y-3">
      <Toolbar
        config={config}
        table={table}
        filters={filters}
        facets={data.facets}
        hasFilters={hasFilters}
        onFilters={onFilters}
        onReset={onReset}
      />

      <div
        className="relative min-w-0 overflow-hidden rounded-xl border"
        aria-busy={fetching}
      >
        {fetching ? (
          <div
            role="progressbar"
            aria-label="Loading…"
            className="absolute inset-x-0 top-0 z-10 h-0.5 overflow-hidden bg-primary/20"
          >
            <div className="h-full w-full animate-pulse bg-primary" />
          </div>
        ) : null}
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id} className="hover:bg-transparent">
                {group.headers.map((header) => {
                  const right = RIGHT_ALIGNED.has(header.column.id);
                  return (
                    <TableHead
                      key={header.id}
                      aria-sort={
                        header.column.getCanSort()
                          ? sortAria(header.column.getIsSorted())
                          : undefined
                      }
                      className={
                        "h-9 text-[11px] tracking-wider text-muted-foreground uppercase" +
                        (right ? " text-right" : "")
                      }
                    >
                      {header.isPlaceholder ? null : (
                        <table.FlexRender header={header} />
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={visibleCount}
                  className="py-12 text-center text-muted-foreground"
                >
                  <p>No holdings match your filters.</p>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={onReset}
                  >
                    Reset
                  </Button>
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => {
                    const right = RIGHT_ALIGNED.has(cell.column.id);
                    return (
                      <TableCell
                        key={cell.id}
                        className={right ? "text-right" : undefined}
                      >
                        <table.FlexRender cell={cell} />
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Pagination table={table} />
    </div>
  );
}
