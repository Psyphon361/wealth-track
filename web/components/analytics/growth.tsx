"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYTICS_GROWTH_PATH } from "@/lib/analytics";
import { apiGet, toApiMessage } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { anyHoldingsVersion } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import type { AnalyticsGrowth } from "@/lib/types";
import { GrowthChangeCard } from "./growth-change-card";
import { GrowthMonthsCard } from "./growth-months-card";

type State =
  | { status: "loading" }
  | { status: "error"; message: string; description: string }
  | { status: "ready"; data: AnalyticsGrowth };

export function Growth() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const hasData = useRef(false);
  const seenVersion = useRef(anyHoldingsVersion());

  useEffect(() => {
    let cancelled = false;
    if (seenVersion.current !== anyHoldingsVersion()) {
      seenVersion.current = anyHoldingsVersion();
      hasData.current = false;
      setState({ status: "loading" });
    }
    apiGet<AnalyticsGrowth>(ANALYTICS_GROWTH_PATH)
      .then((data) => {
        if (cancelled) return;
        hasData.current = true;
        setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (hasData.current) notify.error(err);
        else setState({ status: "error", ...toApiMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  function retry() {
    setState({ status: "loading" });
    setAttempt((a) => a + 1);
  }

  if (state.status === "loading") {
    return (
      <div className="grid gap-3 lg:grid-cols-2" aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-[360px] min-w-0 rounded-xl" />
        <Skeleton className="h-[360px] min-w-0 rounded-xl" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-[13.5px] font-medium text-destructive">{state.message}</p>
          {state.description && (
            <p className="text-[13.5px] text-muted-foreground">{state.description}</p>
          )}
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  const { data } = state;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="min-w-0 [&>*]:h-full">
          <GrowthChangeCard periods={data.periods} />
        </div>
        <div className="min-w-0 [&>*]:h-full">
          <GrowthMonthsCard months={data.months} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        Based on your current holdings.
        {data.stocks_at_cost_before && (
          <>
            {" "}
            Stocks valued at cost before{" "}
            <span className="num">{formatDate(data.stocks_at_cost_before)}</span>.
          </>
        )}
      </p>
    </div>
  );
}
