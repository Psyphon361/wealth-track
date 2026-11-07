import type { ExitSummary, HoldingStatus } from "./types";

/** The fields of a holding row that decide how a closed holding reads. */
export interface ClosedFields {
  status: HoldingStatus;
  settled: boolean;
  exit: ExitSummary | null;
  maturity_amount: number | null;
}

export interface ClosedStatus {
  label: string;
  /** Matured but the payout is not recorded yet: shown with the attention style. */
  attention: boolean;
}

/** Status cell text on the Closed tab: "Matured · Settled", "Matured · Not Settled" or "Sold". */
export function closedStatus(row: Pick<ClosedFields, "status" | "settled">): ClosedStatus {
  if (row.status === "sold") return { label: "Sold", attention: false };
  return row.settled
    ? { label: "Matured · Settled", attention: false }
    : { label: "Matured · Not Settled", attention: true };
}

/** What came back: the recorded amount, else what an unsettled maturity will pay; null when unknown. */
export function receivedAmount(row: Pick<ClosedFields, "exit" | "maturity_amount">): number | null {
  if (row.exit) return row.exit.amount;
  return row.maturity_amount;
}

/** Realised gain of a recorded exit (amount minus cost); null until the exit is recorded. */
export function realisedGain(row: Pick<ClosedFields, "exit">): number | null {
  if (!row.exit) return null;
  return Math.round((row.exit.amount - row.exit.cost) * 100) / 100;
}

/** The "Closed On" date, matching the API sort: exit date, else closed_on, else maturity date; null when none. */
export function closedOnDate(row: {
  exit: Pick<ExitSummary, "date"> | null;
  closed_on: string | null;
  maturity_date?: string | null;
}): string | null {
  return row.exit?.date ?? row.closed_on ?? row.maturity_date ?? null;
}

/** Whether a `status` query value selects the Closed tab (an old "matured" link still does). */
export function isClosedStatusParam(value: string | null): boolean {
  return value === "closed" || value === "matured";
}
