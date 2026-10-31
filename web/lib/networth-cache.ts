import { apiGet } from "./api";
import type { NetWorthHistory, NetWorthRange } from "./types";

export const STALE_MS = 5 * 60 * 1000;

type Entry = { data: NetWorthHistory; fetchedAt: number };

const cache = new Map<NetWorthRange, Entry>();
const inflight = new Map<NetWorthRange, Promise<NetWorthHistory>>();
const listeners = new Set<() => void>();
let generation = 0;

export function isStale(fetchedAt: number, now: number = Date.now()): boolean {
  return now - fetchedAt > STALE_MS;
}

/** Cached data for a range, or undefined when not cached. */
export function getCachedNetWorth(range: NetWorthRange): NetWorthHistory | undefined {
  return cache.get(range)?.data;
}

/** Fetch a range (de-duplicated per range) and store it. Rejects on error. */
export function fetchNetWorth(range: NetWorthRange): Promise<NetWorthHistory> {
  const running = inflight.get(range);
  if (running) return running;
  const gen = generation;
  const p = apiGet<NetWorthHistory>(`/networth/history?range=${range}`)
    .then((data) => {
      if (gen === generation) {
        cache.set(range, { data, fetchedAt: Date.now() });
        listeners.forEach((l) => l());
      }
      return data;
    })
    .finally(() => {
      if (inflight.get(range) === p) inflight.delete(range);
    });
  inflight.set(range, p);
  return p;
}

/**
 * Stale-while-revalidate read: returns cached data immediately when present
 * (refetching in the background if older than 5 minutes), else fetches.
 */
export function loadNetWorth(range: NetWorthRange): Promise<NetWorthHistory> {
  const entry = cache.get(range);
  if (entry) {
    if (isStale(entry.fetchedAt)) fetchNetWorth(range).catch(() => {});
    return Promise.resolve(entry.data);
  }
  return fetchNetWorth(range);
}

let prefetching = false;

/** Sequentially warm every uncached range (errors ignored). One loop at a time. */
export async function prefetchNetWorth(ranges: NetWorthRange[]): Promise<void> {
  if (prefetching) return;
  prefetching = true;
  try {
    for (const r of ranges) {
      if (cache.has(r)) continue;
      try {
        await fetchNetWorth(r);
      } catch {
        // ignored: the range is fetched on demand when selected
      }
    }
  } finally {
    prefetching = false;
  }
}

/** Subscribe to cache changes and invalidations. Returns unsubscribe. */
export function subscribeNetWorth(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Clear everything; mounted subscribers are notified so they refetch. */
export function invalidateNetWorth(): void {
  generation += 1;
  cache.clear();
  inflight.clear();
  listeners.forEach((l) => l());
}
