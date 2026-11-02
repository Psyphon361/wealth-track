import type { AssetType } from "./types";

// Version counters bumped whenever a holding is created, updated or deleted.
// Views that keep data across route hide (stale-while-revalidate) remember the
// version they last loaded at; if it moved, the next reveal shows the loading
// state instead of the stale data.
const versions = new Map<AssetType, number>();
let anyVersion = 0;

/** Record that holdings of this type changed. */
export function markHoldingsStale(type: AssetType): void {
  versions.set(type, (versions.get(type) ?? 0) + 1);
  anyVersion += 1;
  listeners.forEach((l) => l(type));
}

const listeners = new Set<(type: AssetType) => void>();

/** Call back when holdings of a type change while the subscriber is mounted and visible. */
export function subscribeHoldings(listener: (type: AssetType) => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Version for one asset type (grid, details page). */
export function holdingsVersion(type: AssetType): number {
  return versions.get(type) ?? 0;
}

/** Version across all types (dashboard, tab counts). */
export function anyHoldingsVersion(): number {
  return anyVersion;
}
