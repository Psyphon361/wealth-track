"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, toApiMessage } from "@/lib/api";
import { anyHoldingsVersion } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";

export type SectionState<T> =
  | { status: "loading" }
  | { status: "error"; message: string; description: string }
  | { status: "ready"; data: T };

/** Fetches one analytics endpoint; reloads after holdings change; retry on error. */
export function useAnalyticsSection<T>(path: string) {
  const [state, setState] = useState<SectionState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [settledPath, setSettledPath] = useState<string | null>(null);
  const hasData = useRef(false);
  const seenVersion = useRef(anyHoldingsVersion());

  useEffect(() => {
    let cancelled = false;
    if (seenVersion.current !== anyHoldingsVersion()) {
      seenVersion.current = anyHoldingsVersion();
      hasData.current = false;
      setState({ status: "loading" });
    }
    apiGet<T>(path)
      .then((data) => {
        if (cancelled) return;
        hasData.current = true;
        setState({ status: "ready", data });
        setSettledPath(path);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setSettledPath(path);
        if (hasData.current) notify.error(err);
        else setState({ status: "error", ...toApiMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [path, attempt]);

  function retry() {
    setState({ status: "loading" });
    setAttempt((a) => a + 1);
  }

  // True while a changed path is loading and the previous data is still shown.
  const switching = state.status === "ready" && settledPath !== path;

  return { state, retry, switching };
}
