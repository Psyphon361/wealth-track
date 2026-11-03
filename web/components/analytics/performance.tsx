"use client";

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

function ErrorCard({
  state,
  retry,
}: {
  state: Extract<SectionState<unknown>, { status: "error" }>;
  retry: () => void;
}) {
  return (
    <div className="min-w-0">
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

function Skeletons({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} aria-busy="true" aria-label="Loading…">
          <Skeleton className="h-[360px] rounded-xl" />
        </div>
      ))}
    </>
  );
}

export function Performance() {
  const growth = useAnalyticsSection<AnalyticsGrowth>(ANALYTICS_GROWTH_PATH);
  const returns = useAnalyticsSection<AnalyticsReturns>(ANALYTICS_RETURNS_PATH);
  const g = growth.state;
  const r = returns.state;

  const hasTop = r.status === "ready" && (r.data.best.length > 0 || r.data.worst.length > 0);

  return (
    <div className="space-y-3">
      <div className="grid items-start gap-3 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-3">
          {g.status === "loading" && <Skeletons count={2} />}
          {g.status === "error" && <ErrorCard state={g} retry={growth.retry} />}
          {g.status === "ready" && (
            <>
              <GrowthChangeCard periods={g.data.periods} />
              <GrowthMonthsCard months={g.data.months} />
            </>
          )}
          {hasTop && <ReturnsBestWorstCard best={r.data.best} worst={r.data.worst} />}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {r.status === "loading" && <Skeletons count={2} />}
          {r.status === "error" && <ErrorCard state={r} retry={returns.retry} />}
          {r.status === "ready" && (
            <>
              <ReturnsGroupsCard
                overall={r.data.overall}
                byClass={r.data.by_class}
                byType={r.data.by_type}
              />
              <ReturnsCompareCard benchmark={r.data.benchmark ?? null} />
            </>
          )}
        </div>
      </div>

      <div className="space-y-0.5">
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
        {r.status === "ready" && <ReturnsExcluded excluded={r.data.excluded} />}
      </div>
    </div>
  );
}
