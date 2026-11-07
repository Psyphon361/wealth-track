import { changedTypes, type ExitRead } from "@/lib/exits";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import type { AssetType } from "@/lib/types";

/**
 * After a sale, settlement or undo: net worth is stale, and so are the holding's own type and
 * the cash accounts when money moved into one.
 */
export function afterExit(type: AssetType, exit: Pick<ExitRead, "cash_holding_id">): void {
  invalidateNetWorth();
  for (const t of changedTypes(type, exit)) markHoldingsStale(t);
}
