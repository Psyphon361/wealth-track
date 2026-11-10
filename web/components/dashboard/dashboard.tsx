"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiGet, toApiMessage } from "@/lib/api";
import { anyHoldingsVersion } from "@/lib/holdings-cache";
import { notify } from "@/lib/notify";
import type { DashboardResponse } from "@/lib/types";
import { AllocationCard } from "./allocation-card";
import { AttentionCard } from "./attention-card";
import { HoldingsByType } from "./holdings-by-type";
import { NetWorthChart } from "./net-worth-chart";
import { UnsettledPrompt } from "./unsettled-prompt";

type State =
  | { status: "loading" }
  | { status: "error"; message: string; description: string }
  | { status: "ready"; data: DashboardResponse };

export function Dashboard() {
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
    apiGet<DashboardResponse>("/dashboard")
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
        <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
          <Skeleton className="h-[420px] min-w-0 rounded-xl" />
          <Skeleton className="h-[420px] min-w-0 rounded-xl" />
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
  if (data.by_type.every((r) => r.count + r.closed_count === 0)) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
        <p className="text-sm font-medium">No holdings yet</p>
        <p className="text-[13.5px] text-muted-foreground">
          Add your first holding to see your portfolio summary.
        </p>
        <Link href="/add" className={buttonVariants()}>
          Add a holding
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <UnsettledPrompt unsettled={data.unsettled} />
      <AttentionCard attention={data.attention} onChanged={() => setAttempt((a) => a + 1)} />
      <div className="grid gap-3 lg:grid-cols-[2fr_1fr]">
        <div className="min-w-0 [&>*]:h-full">
          <NetWorthChart data={data} />
        </div>
        <div className="min-w-0 [&>*]:h-full">
          <AllocationCard data={data} />
        </div>
      </div>
      <HoldingsByType data={data} />
    </div>
  );
}
