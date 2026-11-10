"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import {
  bucketRateText,
  excludedNotes,
  flagSentences,
  splitPercents,
  splitSubline,
  unrealisedPath,
  type Unrealised,
} from "@/lib/unrealised";
import { LossesCard, RoomCard, TurningCard } from "./gains-unrealised-parts";
import { gainClass } from "./gains-summary";
import { TopProgress } from "./top-progress";
import { useAnalyticsSection } from "./use-analytics-section";

const COLORS = { short: "oklch(0.8 0.15 80)", long: "oklch(0.7 0.15 150)" };

function SoldTodayCard({ data, switching }: { data: Unrealised; switching: boolean }) {
  const [active, setActive] = useState<string | null>(null);
  const s = data.summary;
  const split = splitPercents(s.short_term_net, s.long_term_net);
  const dim = (term: string) => (active !== null && active !== term ? "opacity-40" : "opacity-100");
  const rows = data.buckets.filter((b) => b.gains !== 0 || b.losses !== 0 || b.net !== 0);

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          If You Sold Today
        </p>
        <CardInfo>
          What your open holdings would show as profit or loss if each were closed in full today at
          its current value, split by how it would be taxed. An estimate for information only, not
          tax advice.
        </CardInfo>
      </div>
      <div
        aria-busy={switching}
        className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <div>
          <p className={`num text-xl font-semibold ${gainClass(s.total_gain)}`}>
            {formatINRWhole(s.total_gain)}
          </p>
          <p className="num text-[13.2px] text-muted-foreground">{splitSubline(s)}</p>
        </div>
        {split.short + split.long > 0 && (
          <div className="mt-2 flex h-2.5 gap-0.5" onMouseLeave={() => setActive(null)}>
            {(["short", "long"] as const).map((t) =>
              split[t] > 0 ? (
                <div
                  key={t}
                  onMouseEnter={() => setActive(t)}
                  className={`h-full rounded-full transition-opacity duration-150 ${dim(t)}`}
                  style={{ width: `${split[t]}%`, minWidth: 2, backgroundColor: COLORS[t] }}
                  aria-hidden="true"
                />
              ) : null,
            )}
          </div>
        )}
        {rows.length > 0 && (
          <ul className="flex flex-col" onMouseLeave={() => setActive(null)}>
            {rows.map((b) => {
              const t = b.term === "short" ? "short" : "long";
              return (
                <li
                  key={b.key}
                  onMouseEnter={() => setActive(t)}
                  className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 ${dim(t)}`}
                >
                  <span
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: COLORS[t] }}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">
                    {b.label}
                    <span className="ml-2 text-xs text-muted-foreground">{bucketRateText(b.rate)}</span>
                  </span>
                  <span className={`num shrink-0 text-right ${gainClass(b.net)}`}>
                    {formatINRWhole(b.net)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}

export function GainsUnrealisedCard({ fy }: { fy: number | null }) {
  const { state, retry, switching } = useAnalyticsSection<Unrealised>(unrealisedPath(fy));

  if (state.status === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-[260px] rounded-xl" />
        <Skeleton className="h-[170px] rounded-xl" />
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

  const data = state.data;
  if (data.holdings.length === 0) {
    return (
      <Card size="sm" className="relative min-w-0 gap-1 px-4">
        <TopProgress active={switching} />
        <p className="text-[15.4px] font-medium">No holdings to value</p>
        <p className="text-[13.2px] text-muted-foreground">
          Open stocks, bonds, mutual funds, gold and other holdings show up here.
        </p>
      </Card>
    );
  }

  const notes = [...excludedNotes(data.excluded, data.summary.uncounted_lots), ...flagSentences(data.holdings)];

  return (
    <div className="space-y-3">
      <SoldTodayCard data={data} switching={switching} />
      <RoomCard harvest={data.harvest} switching={switching} />
      <TurningCard lots={data.harvest.turning_long_term} switching={switching} />
      <LossesCard lots={data.harvest.loss_lots} switching={switching} />
      {notes.length > 0 && (
        <div className="space-y-0.5">
          {notes.map((n) => (
            <p key={n} className="text-xs text-muted-foreground">
              {n}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
