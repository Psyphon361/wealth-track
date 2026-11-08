import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { isClosedStatusParam } from "@/lib/closed";
import { holdingsVersion, subscribeHoldings } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import type { HoldingRow, HoldingsResponse, SortDir } from "@/lib/types";
import { filterParamKeys, type FilterDef, type GridConfig } from "./types";

export const DEFAULT_SORT = "current_value";
export const DEFAULT_DIR: SortDir = "desc";

/** Sort keys only the Closed tab offers (the API derives them), and its default: newest closed first. */
export const CLOSED_SORT_KEYS: readonly string[] = [
  "closed_on",
  "received",
  "realised_gain",
];
export const CLOSED_DEFAULT_SORT = "closed_on";

/** The sort a tab starts on: value descending (Active) or newest closed first (Closed). */
function defaultSort(closed: boolean): { sort: string; dir: SortDir } {
  return closed
    ? { sort: CLOSED_DEFAULT_SORT, dir: DEFAULT_DIR }
    : { sort: DEFAULT_SORT, dir: DEFAULT_DIR };
}

export interface HoldingsFilters {
  q: string;
  /** Filter values by query-string key; an empty array means unset. */
  params: Record<string, string[]>;
  sort: string;
  dir: SortDir;
  page: number;
  /** Closed tab selected (only for configs with `statusTabs`). */
  closed: boolean;
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
  config: Pick<GridConfig<HoldingRow>, "filters" | "sortKeys" | "statusTabs">,
): HoldingsFilters {
  const params: Record<string, string[]> = {};
  for (const key of filterParamKeys(config.filters)) {
    const allowed = allowedValues(config.filters, key);
    const values = sp
      .getAll(key)
      .filter((v) => v !== "" && (allowed === null || allowed.includes(v)));
    if (values.length > 0) params[key] = values;
  }
  const closed =
    config.statusTabs === true && isClosedStatusParam(sp.get("status"));
  const fallback = defaultSort(closed);
  const sort = sp.get("sort") ?? "";
  const dir = sp.get("dir");
  const known =
    config.sortKeys.includes(sort) || (closed && CLOSED_SORT_KEYS.includes(sort));
  return {
    q: sp.get("q") ?? "",
    params,
    sort: known ? sort : fallback.sort,
    dir: dir === "asc" || dir === "desc" ? dir : fallback.dir,
    page: posInt(sp.get("page"), 1),
    closed,
  };
}

/** Serialise to a query string, omitting params at their default. */
export function toQueryString(f: HoldingsFilters): string {
  const sp = new URLSearchParams();
  if (f.q.trim()) sp.set("q", f.q.trim());
  for (const [key, values] of Object.entries(f.params)) {
    values.forEach((v) => sp.append(key, v));
  }
  const fallback = defaultSort(f.closed);
  if (f.sort !== fallback.sort || f.dir !== fallback.dir) {
    sp.set("sort", f.sort);
    sp.set("dir", f.dir);
  }
  if (f.page !== 1) sp.set("page", String(f.page));
  if (f.closed) sp.set("status", "closed");
  return sp.toString();
}

/** Query string sent to the API: the Active tab sends status=active explicitly. */
function toApiQueryString(
  f: HoldingsFilters,
  config: Pick<GridConfig<HoldingRow>, "statusTabs">,
): string {
  const query = toQueryString(f);
  if (!config.statusTabs || f.closed) return query;
  return query ? `${query}&status=active` : "status=active";
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
  const qs = useMemo(
    () => toApiQueryString(filters, config),
    [filters, config],
  );
  const endpoint = `/holdings/${config.type}`;

  const [data, setData] = useState<HoldingsResponse<TRow> | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  // Query string of the last request that completed (success or failure).
  const [settled, setSettled] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  // Status tab (closed or not) the shown `data` belongs to.
  const [dataClosed, setDataClosed] = useState(false);
  const requestId = useRef(0);
  const hasData = useRef(false);
  const seenVersion = useRef(holdingsVersion(config.type));
  const closedNow = filters.closed;

  const load = useCallback(
    (query: string, closed: boolean) => {
      const id = ++requestId.current;
      // Data already shown (e.g. route revealed again): refresh in the background.
      if (hasData.current) setRefreshing(true);
      apiGet<HoldingsResponse<TRow>>(`${endpoint}${query ? `?${query}` : ""}`)
        .then((res) => {
          if (id !== requestId.current) return;
          hasData.current = true;
          setData(res);
          setDataClosed(closed);
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
    // A holding of this type changed outside the grid since we last loaded:
    // drop the cached rows so the loading state shows until fresh data arrives.
    if (seenVersion.current !== holdingsVersion(config.type)) {
      seenVersion.current = holdingsVersion(config.type);
      hasData.current = false;
      setData(null);
      setError(null);
    }
    load(qs, closedNow);
    return () => {
      counter.current++;
    };
  }, [qs, load, config.type, closedNow]);

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
    (sort: string, dir: SortDir) => {
      // The header's "back to default" step asks for the Active default; on the Closed tab
      // that column is not shown, so go back to the Closed default instead.
      const reset = filters.closed && sort === DEFAULT_SORT;
      navigate({
        ...filters,
        ...(reset ? defaultSort(true) : { sort, dir }),
        page: 1,
      });
    },
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

  /** Switch Active / Closed tab; resets to page 1 and to that tab's default sort. */
  const setClosed = useCallback(
    (closed: boolean) =>
      navigate({ ...filters, ...defaultSort(closed), closed, page: 1 }),
    [navigate, filters],
  );

  const refetch = useCallback(() => {
    // In-grid change: rows stay, and nothing is pending for this type.
    seenVersion.current = holdingsVersion(config.type);
    setRefreshing(true);
    load(qs, closedNow);
  }, [load, qs, config.type, closedNow]);

  // A change to this type made elsewhere while the grid is visible (e.g. a restore
  // from the Recently deleted page): reload in place. Hidden grids
  // (Activity) have their effects torn down, so they catch up on reveal above.
  useEffect(
    () =>
      subscribeHoldings((type) => {
        if (type === config.type && seenVersion.current !== holdingsVersion(type)) {
          refetch();
        }
      }),
    [config.type, refetch],
  );

  const retry = useCallback(() => {
    setError(null);
    setSettled(null);
    load(qs, closedNow);
  }, [load, qs, closedNow]);

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
                ...(filters.closed
                  ? {
                      closed_count: Math.max(0, prev.summary.closed_count - 1),
                      matured_count: Math.max(0, prev.summary.matured_count - 1),
                    }
                  : { count: Math.max(0, prev.summary.count - 1) }),
              },
            }
          : prev,
      );
      return () => setData(snapshot);
    },
    [data, filters.closed],
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
  // The shown data belongs to the other status tab and its replacement is loading:
  // callers show skeletons instead of the old tab's rows and figures.
  const switching =
    status === "ready" && dataClosed !== filters.closed && settled !== qs;

  return {
    filters,
    data,
    dataClosed,
    error,
    status,
    fetching,
    switching,
    setFilters,
    setSort,
    setPage,
    setClosed,
    resetFilters,
    refetch,
    retry,
    removeItem,
  };
}
