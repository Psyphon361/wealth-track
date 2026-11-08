import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import { notify } from "@/lib/notify";
import type { Sip } from "@/lib/types";

/**
 * The user's SIPs (all, or one holding's). Loads when mounted and again each
 * time the view is revealed; `reload` refreshes in place without clearing
 * the list.
 */
export function useSips(mutualFundId?: number) {
  const [sips, setSips] = useState<Sip[] | null>(null);
  const [error, setError] = useState<ApiMessage | null>(null);
  const [reloading, setReloading] = useState(false);
  const requestId = useRef(0);
  const hasData = useRef(false);

  const load = useCallback(() => {
    const id = ++requestId.current;
    const query =
      mutualFundId === undefined ? "" : `?mutual_fund_id=${mutualFundId}`;
    if (hasData.current) setReloading(true);
    apiGet<Sip[]>(`/sips${query}`)
      .then((res) => {
        if (id !== requestId.current) return;
        hasData.current = true;
        setSips(res);
        setError(null);
        setReloading(false);
      })
      .catch((err: unknown) => {
        if (id !== requestId.current) return;
        setReloading(false);
        if (hasData.current) notify.error(err);
        else setError(toApiMessage(err));
      });
  }, [mutualFundId]);

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

  return { sips, error, reloading, reload: load, retry };
}
