import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { anyHoldingsVersion } from "@/lib/holdings-cache";
import { prepareIndex, type PreparedItem } from "@/lib/search/rank";
import { clearRecents } from "@/lib/search/recents";
import type { SearchIndexItem } from "@/lib/search/types";

// Module-level store: it outlives route changes (routes stay mounted) and is shared by every
// consumer. The index is fetched once, kept in memory, and ranked in the browser.

export const SEARCH_STALE_MS = 5 * 60 * 1000;

export interface SearchState {
  /** Prepared items, null until the first successful load. */
  index: PreparedItem[] | null;
  /** "type:id" to item, for resolving recents. */
  byKey: Map<string, SearchIndexItem> | null;
  /** A request is in flight. */
  loading: boolean;
  /** Last failure. Only shown when there is no data to fall back on. */
  error: ApiMessage | null;
  /** Date.now() of the last successful load. */
  fetchedAt: number;
}

const INITIAL: SearchState = { index: null, byKey: null, loading: false, error: null, fetchedAt: 0 };

let state: SearchState = INITIAL;
let generation = 0;
let inflight: Promise<void> | null = null;
/** anyHoldingsVersion() when the data in `state` was requested. */
let fetchedVersion = -1;
const listeners = new Set<() => void>();

function update(patch: Partial<SearchState>): void {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

export function getSearchState(): SearchState {
  return state;
}

export function getServerSearchState(): SearchState {
  return INITIAL;
}

export function subscribeSearch(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

async function load(gen: number): Promise<boolean> {
  const startVersion = anyHoldingsVersion();
  try {
    const { items } = await apiGet<{ items: SearchIndexItem[] }>("/search/index");
    if (gen !== generation) return false;
    const byKey = new Map<string, SearchIndexItem>();
    for (const item of items) byKey.set(`${item.type}:${item.id}`, item);
    fetchedVersion = startVersion;
    update({ index: prepareIndex(items), byKey, loading: false, error: null, fetchedAt: Date.now() });
    // A holding changed while this request was running: its answer may predate the change.
    return anyHoldingsVersion() !== startVersion;
  } catch (err) {
    if (gen !== generation) return false;
    update({ loading: false, error: toApiMessage(err) });
    return false;
  }
}

/** Fetches the index. A request already in flight is shared rather than repeated. */
export function fetchSearchIndex(): Promise<void> {
  if (inflight) return inflight;
  const gen = generation;
  update({ loading: true });
  const p: Promise<void> = load(gen).then((again) => {
    if (inflight === p) inflight = null;
    if (again && gen === generation) return fetchSearchIndex();
  });
  inflight = p;
  return p;
}

/** Fetches when there is no data yet, holdings changed since the last fetch, or the data is old. */
export function refreshSearchIndexIfNeeded(): void {
  if (inflight) return;
  const stale =
    state.index === null ||
    fetchedVersion !== anyHoldingsVersion() ||
    Date.now() - state.fetchedAt > SEARCH_STALE_MS;
  if (stale) void fetchSearchIndex();
}

/** Loads the index when the browser is idle. Returns a cancel function. */
export function preloadSearchIndex(): () => void {
  if (typeof window.requestIdleCallback === "function") {
    const id = window.requestIdleCallback(() => refreshSearchIndexIfNeeded(), { timeout: 5000 });
    return () => window.cancelIdleCallback(id);
  }
  const id = window.setTimeout(refreshSearchIndexIfNeeded, 1500);
  return () => window.clearTimeout(id);
}

/** Forgets the index and recents (logout). A response that arrives later is dropped. */
export function clearSearchData(): void {
  generation += 1;
  inflight = null;
  fetchedVersion = -1;
  clearRecents();
  state = INITIAL;
  listeners.forEach((l) => l());
}
