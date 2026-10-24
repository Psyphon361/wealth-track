import { toast } from "sonner";

const ERROR_DURATION = 6000;

function message(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

/** Best-effort display name for any asset record. */
export function recordName(record: object): string | undefined {
  const r = record as Record<string, unknown>;
  for (const key of ["scheme_name", "name", "bank"]) {
    const v = r[key];
    if (typeof v === "string" && v) return v;
  }
  return undefined;
}

export const notify = {
  saving: (): string | number => toast.loading("Saving…"),
  added: (name?: string, id?: string | number) =>
    toast.success("Holding added", { id, description: name }),
  saved: (name?: string, id?: string | number) =>
    toast.success("Changes saved", { id, description: name }),
  saveFailed: (err: unknown, id?: string | number) =>
    toast.error("Couldn't save", {
      id,
      description: message(err, "Something went wrong"),
      duration: ERROR_DURATION,
    }),
  deleted: (name?: string) =>
    toast.success("Holding deleted", { description: name }),
  deleteFailed: (err: unknown) =>
    toast.error("Couldn't delete", {
      description: message(err, "Something went wrong"),
      duration: ERROR_DURATION,
    }),
  refreshFailed: (err: unknown) =>
    toast.error("Couldn't refresh", {
      description: message(err, "Failed to load portfolio"),
      duration: ERROR_DURATION,
    }),
};
