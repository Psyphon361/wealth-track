import { apiPost, type ApiMessage } from "@/lib/api";
import { markHoldingsStale } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { notify } from "@/lib/notify";
import type { AssetType } from "@/lib/types";

/** Restore a soft-deleted holding. Shows the API toast; resolves true on success. */
export async function restoreHolding(type: AssetType, id: number): Promise<boolean> {
  try {
    const res = await apiPost<ApiMessage>(`/assets/${type}/${id}/restore`, {});
    invalidateNetWorth();
    markHoldingsStale(type);
    notify.success(res);
    return true;
  } catch (err: unknown) {
    notify.error(err);
    return false;
  }
}
