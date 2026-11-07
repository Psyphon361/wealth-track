/**
 * One-shot prefill handoff for "Reinvest": the exits UI stores what to prefill,
 * the Add form takes it once on mount. Lives in sessionStorage, not the URL.
 */

export type ReinvestPrefill = {
  /** An asset type slug, or "*" when the user still has to pick one. */
  type: string;
  amount: number;
  date: string;
  cash_id: number;
  cash_name: string;
  from_exit_id?: number;
};

const KEY = "wt.reinvest";

export function setReinvest(p: ReinvestPrefill): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    // Storage unavailable: the Add form simply opens blank.
  }
}

function isPrefill(v: unknown): v is ReinvestPrefill {
  if (!v || typeof v !== "object") return false;
  const p = v as Record<string, unknown>;
  return (
    typeof p.type === "string" &&
    typeof p.amount === "number" &&
    typeof p.date === "string" &&
    typeof p.cash_id === "number" &&
    typeof p.cash_name === "string" &&
    (p.from_exit_id === undefined || typeof p.from_exit_id === "number")
  );
}

function readPrefill(): ReinvestPrefill | null {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isPrefill(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** The pending prefill without clearing it (the /add gallery note). */
export function peekReinvest(): ReinvestPrefill | null {
  return readPrefill();
}

/**
 * Returns and clears the prefill when it is for `type` or for any type (`"*"`, set by
 * "More…"); the returned prefill carries the requested type.
 */
export function takeReinvest(type: string): ReinvestPrefill | null {
  const p = readPrefill();
  if (!p || (p.type !== type && p.type !== "*")) return null;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing to clear.
  }
  return { ...p, type };
}
