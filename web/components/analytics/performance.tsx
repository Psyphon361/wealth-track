"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYTICS_GROWTH_PATH, ANALYTICS_RETURNS_PATH } from "@/lib/analytics";
import { formatDate } from "@/lib/format";
import type { AnalyticsGrowth, AnalyticsReturns } from "@/lib/types";
import { GrowthChangeCard } from "./growth-change-card";
import { GrowthMonthsCard } from "./growth-months-card";
import { ReturnsBestWorstCard } from "./returns-best-worst-card";
import { ReturnsCompareCard } from "./returns-compare-card";
import { ReturnsExcluded } from "./returns-excluded";
import { ReturnsGroupsCard } from "./returns-groups-card";
import { useAnalyticsSection, type SectionState } from "./use-analytics-section";

// Phone order: growth story first, then returns. From lg: two columns.
const SLOT = {
  change: "order-1 lg:order-none lg:col-start-1 lg:row-start-1",
  months: "order-2 lg:order-none lg:col-start-1 lg:row-start-2",
  groups: "order-3 lg:order-none lg:col-start-2 lg:row-start-1",
  compare: "order-4 lg:order-none lg:col-start-2 lg:row-start-2",
  best: "order-5 lg:order-none lg:col-span-2 lg:col-start-1 lg:row-start-3",
};

function Slot({ className, children }: { className: string; children: ReactNode }) {
  return <div className={`min-w-0 [&>*]:h-full ${className}`}>{children}</div>;
}

function ErrorCard({
  state,
  retry,
  className,
}: {
  state: Extract<SectionState<unknown>, { status: "error" }>;
  retry: () => void;
  className: string;
}) {
  return (
    <div className={`min-w-0 lg:row-span-2 ${className}`}>
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
    </div>
  );
}

function Loading({ first, second }: { first: string; second: string }) {
  return (
    <>
      <div className={`min-w-0 ${first}`} aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-[360px] rounded-xl" />
      </div>
      <div className={`min-w-0 ${second}`} aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-[360px] rounded-xl" />
      </div>
    </>
  );
}

export function Performance() {
  const growth = useAnalyticsSection<AnalyticsGrowth>(ANALYTICS_GROWTH_PATH);
  const returns = useAnalyticsSection<AnalyticsReturns>(ANALYTICS_RETURNS_PATH);
  const g = growth.state;
  const r = returns.state;

  return (
    <div className="space-y-3">
      <div className="grid gap-3 lg:grid-cols-2">
        {g.status === "loading" && <Loading first={SLOT.change} second={SLOT.months} />}
        {g.status === "error" && (
          <ErrorCard state={g} retry={growth.retry} className={SLOT.change} />
        )}
        {g.status === "ready" && (
          <>
            <Slot className={SLOT.change}>
              <GrowthChangeCard periods={g.data.periods} />
            </Slot>
            <Slot className={SLOT.months}>
              <GrowthMonthsCard months={g.data.months} />
            </Slot>
          </>
        )}

        {r.status === "loading" && <Loading first={SLOT.groups} second={SLOT.compare} />}
        {r.status === "error" && (
          <ErrorCard state={r} retry={returns.retry} className={SLOT.groups} />
        )}
        {r.status === "ready" && (
          <>
            <Slot className={SLOT.groups}>
              <ReturnsGroupsCard
                overall={r.data.overall}
                byClass={r.data.by_class}
                byType={r.data.by_type}
              />
            </Slot>
            <Slot className={SLOT.compare}>
              <ReturnsCompareCard benchmark={r.data.benchmark ?? null} />
            </Slot>
            {(r.data.best.length > 0 || r.data.worst.length > 0) && (
              <div className={`min-w-0 ${SLOT.best}`}>
                <ReturnsBestWorstCard best={r.data.best} worst={r.data.worst} />
              </div>
            )}
          </>
        )}
      </div>

      {g.status === "ready" && (
        <p className="text-xs text-muted-foreground">
          Based on your current holdings.
          {g.data.stocks_at_cost_before && (
            <>
              {" "}
              Stocks valued at cost before{" "}
              <span className="num">{formatDate(g.data.stocks_at_cost_before)}</span>.
            </>
          )}
        </p>
      )}
      {r.status === "ready" && <ReturnsExcluded excluded={r.data.excluded} rates={r.data.rates} />}
    </div>
  );
}
