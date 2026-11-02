/** Recent searches and recently opened holdings, kept in localStorage. */

export const RECENTS_KEY = "wt.search.recent";
export const MAX_RECENTS = 8;
const MAX_QUERY_LENGTH = 100;

export interface Recents {
  /** Search texts, newest first. */
  queries: string[];
  /** Opened holdings as "type:id", newest first. */
  opened: string[];
}

export const EMPTY_RECENTS: Recents = { queries: [], opened: [] };

/** Puts `value` first and drops any case-insensitive duplicate. Blank values change nothing. */
export function pushRecent(list: readonly string[], value: string, max = MAX_RECENTS): string[] {
  const v = value.trim();
  if (!v) return list.slice(0, max);
  const key = v.toLowerCase();
  return [v, ...list.filter((x) => x.toLowerCase() !== key)].slice(0, max);
}

export function removeRecent(list: readonly string[], value: string): string[] {
  const key = value.trim().toLowerCase();
  return list.filter((x) => x.toLowerCase() !== key);
}

function cleanList(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const v of raw) {
    if (typeof v !== "string") continue;
    const t = v.trim();
    if (!t || out.some((x) => x.toLowerCase() === t.toLowerCase())) continue;
    out.push(t);
    if (out.length === MAX_RECENTS) break;
  }
  return out;
}

/** Parses the stored text. Anything that is not the expected shape gives empty lists. */
export function parseRecents(raw: string | null): Recents {
  if (!raw) return EMPTY_RECENTS;
  try {
    const data: unknown = JSON.parse(raw);
    if (!data || typeof data !== "object" || Array.isArray(data)) return EMPTY_RECENTS;
    const { queries, opened } = data as Record<string, unknown>;
    return { queries: cleanList(queries), opened: cleanList(opened) };
  } catch {
    return EMPTY_RECENTS;
  }
}

// Storage and change notification. Every storage access is guarded: private modes and
// disabled storage throw, in which case the lists live in memory for the session.

let memory: string | null = null;
let cachedRaw: string | null | undefined;
let cached: Recents = EMPTY_RECENTS;
const listeners = new Set<() => void>();

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(RECENTS_KEY);
  } catch {
    return memory;
  }
}

function writeRaw(raw: string | null): void {
  memory = raw;
  try {
    if (raw === null) window.localStorage.removeItem(RECENTS_KEY);
    else window.localStorage.setItem(RECENTS_KEY, raw);
  } catch {
    // kept in memory only
  }
  listeners.forEach((l) => l());
}

/** Current lists. The same object is returned until the stored text changes. */
export function getRecents(): Recents {
  const raw = readRaw();
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cached = parseRecents(raw);
  }
  return cached;
}

export function subscribeRecents(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === null || e.key === RECENTS_KEY) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

function save(next: Recents): void {
  writeRaw(JSON.stringify(next));
}

export function saveRecentQuery(query: string): void {
  const q = query.trim().replace(/\s+/g, " ").slice(0, MAX_QUERY_LENGTH);
  if (!q) return;
  const cur = getRecents();
  save({ ...cur, queries: pushRecent(cur.queries, q) });
}

export function saveRecentOpened(key: string): void {
  const cur = getRecents();
  save({ ...cur, opened: pushRecent(cur.opened, key) });
}

export function removeRecentQuery(query: string): void {
  const cur = getRecents();
  save({ ...cur, queries: removeRecent(cur.queries, query) });
}

export function removeRecentOpened(key: string): void {
  const cur = getRecents();
  save({ ...cur, opened: removeRecent(cur.opened, key) });
}

export function clearRecentQueries(): void {
  save({ ...getRecents(), queries: [] });
}

/** Forgets everything (used on logout). */
export function clearRecents(): void {
  writeRaw(null);
}
