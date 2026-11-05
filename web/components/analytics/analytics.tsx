"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYTICS_PATH } from "@/lib/analytics";
import { apiGet, toApiMessage } from "@/lib/api";
import { anyHoldingsVersion } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import type { AnalyticsOverview } from "@/lib/types";
import { AllocationCard } from "./allocation-card";
import { BankSafetyCard } from "./bank-safety-card";
import { ComingUpCard } from "./coming-up-card";
import { ConcentrationCard } from "./concentration-card";
import { InflowsCard } from "./inflows-card";
import { LiquidityCard } from "./liquidity-card";
import { DataHealthStrip, newestPriceDate } from "./data-health-strip";
import { formatDate } from "@/lib/format";

type State =
  | { status: "loading" }
  | { status: "error"; message: string; description: string }
  | { status: "ready"; data: AnalyticsOverview };

function isEmpty(data: AnalyticsOverview): boolean {
  return data.allocation.including_retirement.classes.length === 0;
}

export function Analytics() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const hasData = useRef(false);
  const seenVersion = useRef(anyHoldingsVersion());

  useEffect(() => {
    let cancelled = false;
    // Holdings changed since the last load: show the skeleton, not stale data.
    if (seenVersion.current !== anyHoldingsVersion()) {
      seenVersion.current = anyHoldingsVersion();
      hasData.current = false;
      setState({ status: "loading" });
    }
    apiGet<AnalyticsOverview>(ANALYTICS_PATH)
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
      <div className="space-y-3" aria-busy="true" aria-label="Loading…">
        <div className="grid gap-3 lg:grid-cols-2">
          <Skeleton className="h-[420px] min-w-0 rounded-xl" />
          <Skeleton className="h-[420px] min-w-0 rounded-xl" />
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          <Skeleton className="h-48 min-w-0 rounded-xl" />
          <Skeleton className="h-48 min-w-0 rounded-xl" />
        </div>
        <Skeleton className="h-64 rounded-xl" />
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
  if (isEmpty(data)) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
        <p className="text-sm font-medium">No holdings yet</p>
        <p className="text-[13.5px] text-muted-foreground">
          Add your first holding to see your analytics.
        </p>
        <Link href="/add" className={buttonVariants()}>
          Add a holding
        </Link>
      </div>
    );
  }

  const newest = newestPriceDate(data.data_health);

  return (
    <div className="space-y-3">
      <DataHealthStrip health={data.data_health} />
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="min-w-0 [&>*]:h-full">
          <AllocationCard allocation={data.allocation} />
        </div>
        <div className="min-w-0 [&>*]:h-full">
          <LiquidityCard liquidity={data.liquidity} />
        </div>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="min-w-0 [&>*]:h-full">
          <BankSafetyCard bankSafety={data.bank_safety} />
        </div>
        <div className="min-w-0 [&>*]:h-full">
          <ComingUpCard comingUp={data.coming_up} />
        </div>
      </div>
      <InflowsCard />
      <ConcentrationCard concentration={data.concentration} />
      {newest && (
        <p className="text-right text-xs text-muted-foreground">
          Prices as of <span className="num">{formatDate(newest)}</span>
        </p>
      )}
    </div>
  );
}
