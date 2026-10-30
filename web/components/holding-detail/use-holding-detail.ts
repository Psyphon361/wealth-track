import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
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
    load();
    return () => {
      counter.current++;
    };
  }, [load]);

  const retry = useCallback(() => {
    setError(null);
    load();
  }, [load]);

  return { data, error, refetch: load, retry };
}
