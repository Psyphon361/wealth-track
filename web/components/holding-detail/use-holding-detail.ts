import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { holdingsVersion } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import type {
  AssetType,
  HoldingDetailResponse,
  HoldingRow,
} from "@/lib/types";

export function useHoldingDetail<TRow extends HoldingRow>(
  type: AssetType,
  id: number,
) {
  const [data, setData] = useState<HoldingDetailResponse<TRow> | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  const requestId = useRef(0);
  const hasData = useRef(false);
  const seenVersion = useRef(holdingsVersion(type));

  const load = useCallback(() => {
    const rid = ++requestId.current;
    apiGet<HoldingDetailResponse<TRow>>(`/holdings/${type}/${id}`)
      .then((res) => {
        if (rid !== requestId.current) return;
        hasData.current = true;
        setData(res);
        setError(null);
      })
      .catch((err: unknown) => {
        if (rid !== requestId.current) return;
        if (hasData.current) notify.error(err);
        else setError(toApiMessage(err));
      });
  }, [type, id]);

  useEffect(() => {
    const counter = requestId;
    // This type was changed outside this page (grid edit, import): show the
    // loading state on reveal instead of the old values.
    if (seenVersion.current !== holdingsVersion(type)) {
      seenVersion.current = holdingsVersion(type);
      hasData.current = false;
      setData(null);
      setError(null);
    }
    load();
    return () => {
      counter.current++;
    };
  }, [load, type]);

  // In-page edit: refresh in place and clear the pending mark.
  const refetch = useCallback(() => {
    seenVersion.current = holdingsVersion(type);
    load();
  }, [load, type]);

  const retry = useCallback(() => {
    setError(null);
    load();
  }, [load]);

  return { data, error, refetch, retry };
}
