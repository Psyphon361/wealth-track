"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { apiGet } from "@/lib/api";
import type { DashboardResponse } from "@/lib/types";
import { SummaryCards } from "./summary-cards";
import { HoldingsByType } from "./holdings-by-type";

type State =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: DashboardResponse };

function Skeleton({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-muted ${className}`} />;
}

export function Dashboard() {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<DashboardResponse>("/dashboard")
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setState({
            status: "error",
            message:
              err instanceof Error ? err.message : "Failed to load dashboard",
          });
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
      <div className="space-y-6" aria-busy="true" aria-label="Loading…">
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <p className="text-sm text-destructive">{state.message}</p>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  const { data } = state;
  if (data.by_type.every((r) => r.count === 0)) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed py-16 text-center">
        <p className="text-lg font-medium">No holdings yet</p>
        <p className="text-sm text-muted-foreground">
          Add your first holding to see your portfolio summary.
        </p>
        <Link href="/add" className={buttonVariants()}>
          Add a holding
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <SummaryCards data={data} />
      <HoldingsByType data={data} />
    </div>
  );
}
