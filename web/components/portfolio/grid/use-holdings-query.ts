import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { notify } from "@/lib/notify";
import type { HoldingRow, HoldingsResponse, SortDir } from "@/lib/types";
import { filterParamKeys, type FilterDef, type GridConfig } from "./types";

export const DEFAULT_SORT = "current_value";
export const DEFAULT_DIR: SortDir = "desc";

export interface HoldingsFilters {
  q: string;
  /** Filter values by query-string key; an empty array means unset. */
  params: Record<string, string[]>;
  sort: string;
  dir: SortDir;
  page: number;
}

export interface FilterPatch {
  q?: string;
  params?: Record<string, string[]>;
}

/** Allowed values for an enum facet, or null for free text / single values. */
function allowedValues(defs: FilterDef[], key: string): string[] | null {
  const def = defs.find((d) => d.kind === "facet" && d.key === key);
  return def && def.kind === "facet" && def.labels
    ? Object.keys(def.labels)
    : null;
}

function posInt(v: string | null, fallback: number): number {
  const n = Number(v);
  return Number.isInteger(n) && n >= 1 ? n : fallback;
}

export function parseFilters(
  sp: URLSearchParams,
  config: Pick<GridConfig<HoldingRow>, "filters" | "sortKeys">,
): HoldingsFilters {
  const params: Record<string, string[]> = {};
  for (const key of filterParamKeys(config.filters)) {
    const allowed = allowedValues(config.filters, key);
    const values = sp
      .getAll(key)
      .filter((v) => v !== "" && (allowed === null || allowed.includes(v)));
    if (values.length > 0) params[key] = values;
  }
  const sort = sp.get("sort") ?? "";
  const dir = sp.get("dir");
  return {
    q: sp.get("q") ?? "",
    params,
    sort: config.sortKeys.includes(sort) ? sort : DEFAULT_SORT,
    dir: dir === "asc" || dir === "desc" ? dir : DEFAULT_DIR,
    page: posInt(sp.get("page"), 1),
  };
}

/** Serialise to a query string, omitting params at their default. */
export function toQueryString(f: HoldingsFilters): string {
  const sp = new URLSearchParams();
  if (f.q.trim()) sp.set("q", f.q.trim());
  for (const [key, values] of Object.entries(f.params)) {
    values.forEach((v) => sp.append(key, v));
  }
  if (f.sort !== DEFAULT_SORT || f.dir !== DEFAULT_DIR) {
    sp.set("sort", f.sort);
    sp.set("dir", f.dir);
  }
  if (f.page !== 1) sp.set("page", String(f.page));
  return sp.toString();
}

export function hasActiveFilters(f: HoldingsFilters): boolean {
  return (
    f.q.trim() !== "" ||
    Object.values(f.params).some((values) => values.length > 0)
  );
}

export type QueryStatus = "loading" | "error" | "ready";

export function useHoldingsQuery<TRow extends HoldingRow>(
  config: GridConfig<TRow>,
) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const paramString = searchParams.toString();
  const filters = useMemo(
    () => parseFilters(new URLSearchParams(paramString), config),
    [paramString, config],
  );
  const qs = useMemo(() => toQueryString(filters), [filters]);
  const endpoint = `/holdings/${config.type}`;

  const [data, setData] = useState<HoldingsResponse<TRow> | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  // Query string of the last request that completed (success or failure).
  const [settled, setSettled] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const requestId = useRef(0);
  const hasData = useRef(false);

  const load = useCallback(
    (query: string) => {
      const id = ++requestId.current;
      apiGet<HoldingsResponse<TRow>>(`${endpoint}${query ? `?${query}` : ""}`)
        .then((res) => {
          if (id !== requestId.current) return;
          hasData.current = true;
          setData(res);
          setError(null);
          setSettled(query);
          setRefreshing(false);
        })
        .catch((err: unknown) => {
          if (id !== requestId.current) return;
          setSettled(query);
          setRefreshing(false);
          if (hasData.current) notify.error(err);
          else setError(toApiMessage(err));
        });
    },
    [endpoint],
  );

  useEffect(() => {
    const counter = requestId;
    load(qs);
    return () => {
      counter.current++;
    };
  }, [qs, load]);

  const navigate = useCallback(
    (next: HoldingsFilters) => {
      const query = toQueryString(next);
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    },
    [router, pathname],
  );

  /** Change filters/search; resets to page 1. */
  const setFilters = useCallback(
    (patch: FilterPatch) =>
      navigate({
        ...filters,
        q: patch.q ?? filters.q,
        params: { ...filters.params, ...patch.params },
        page: 1,
      }),
    [navigate, filters],
  );

  const setSort = useCallback(
    (sort: string, dir: SortDir) =>
      navigate({ ...filters, sort, dir, page: 1 }),
    [navigate, filters],
  );

  const setPage = useCallback(
    (page: number) => navigate({ ...filters, page }),
    [navigate, filters],
  );

  const resetFilters = useCallback(
    () => navigate({ ...filters, q: "", params: {}, page: 1 }),
    [navigate, filters],
  );

  const refetch = useCallback(() => {
    setRefreshing(true);
    load(qs);
  }, [load, qs]);

  const retry = useCallback(() => {
    setError(null);
    setSettled(null);
    load(qs);
  }, [load, qs]);

  /** Optimistically drop a row; returns a function that restores the snapshot. */
  const removeItem = useCallback(
    (id: number) => {
      const snapshot = data;
      // Invalidate any in-flight request so a stale list can't reappear.
      requestId.current++;
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.filter((i) => i.id !== id),
              total: Math.max(0, prev.total - 1),
              summary: {
                ...prev.summary,
                count: Math.max(0, prev.summary.count - 1),
              },
            }
          : prev,
      );
      return () => setData(snapshot);
    },
    [data],
  );

  // If the current page no longer exists (e.g. after deletes), go to the last one.
  const outOfRange =
    data !== null &&
    settled === qs &&
    data.items.length === 0 &&
    data.total > 0 &&
    filters.page > data.page_count;
  const lastPage = data?.page_count ?? 1;
  useEffect(() => {
    if (outOfRange) setPage(lastPage);
  }, [outOfRange, lastPage, setPage]);

  const status: QueryStatus = data ? "ready" : error ? "error" : "loading";
  const fetching = status === "ready" && (settled !== qs || refreshing);

  return {
    filters,
    data,
    error,
    status,
    fetching,
    setFilters,
    setSort,
    setPage,
    resetFilters,
    refetch,
    retry,
    removeItem,
  };
}
