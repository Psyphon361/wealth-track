import type { AssetType } from "./types";

// Version counters bumped whenever a holding is created, updated or deleted.
// Views that keep data across route hide (stale-while-revalidate) remember the
// version they last loaded at; if it moved, the next reveal shows the loading
// state instead of the stale data.
const versions = new Map<AssetType, number>();
let anyVersion = 0;

/**
 * Types to mark stale after a holding changes: its own type, plus cash when
 * money moved through a "Paid from" cash account (debit, refund or re-debit).
 */
export function staleTypes(type: AssetType, paidFrom: boolean): AssetType[] {
  return paidFrom && type !== "cash" ? [type, "cash"] : [type];
}

/** Mark every type affected by a change (see staleTypes). */
export function markHoldingsChanged(type: AssetType, paidFrom: boolean): void {
  for (const t of staleTypes(type, paidFrom)) markHoldingsStale(t);
}

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
