import { ApiError } from "./api";

/** One existing holding the API says the new one looks like. */
export interface DuplicateMatch {
  id: number;
  name: string;
}

/**
 * The matching holdings of an HTTP 409 "looks like a holding you already have"
 * error, or null when the error is anything else.
 */
export function readDuplicates(err: unknown): DuplicateMatch[] | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  if (!Array.isArray(err.duplicates)) return null;
  const out: DuplicateMatch[] = [];
  for (const d of err.duplicates as unknown[]) {
    if (!d || typeof d !== "object") continue;
    const { id, name } = d as { id?: unknown; name?: unknown };
    if (typeof id === "number" && typeof name === "string") {
      out.push({ id, name });
    }
  }
  return out.length ? out : null;
}

/** The same create path with the duplicate warning acknowledged. */
export function confirmDuplicatePath(path: string): string {
  return `${path}${path.includes("?") ? "&" : "?"}confirm_duplicate=true`;
}

/** Details page of an existing holding. */
export function duplicateHref(type: string, id: number): string {
  return `/portfolio/${type}/${id}`;
}
