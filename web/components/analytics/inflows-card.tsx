"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CardInfo } from "@/components/analytics/card-info";
import { TopProgress } from "@/components/analytics/top-progress";
import { useAnalyticsSection } from "@/components/analytics/use-analytics-section";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDate, formatINRWhole } from "@/lib/format";
import { MONEY_COLOR, columnLabel, monthLabel } from "@/lib/growth";
import {
  defaultMonth,
  filterInflows,
  inflowAmountText,
  inflowColumns,
  inflowHref,
  inflowKindLabel,
  inflowTotals,
  inflowTypeLabel,
  inflowsPath,
  itemTotal,
  sortedItems,
  type AnalyticsInflows,
  type InflowMonthsCount,
} from "@/lib/inflows";

const PERIODS = [
  { value: "12", label: "Next 12 Months" },
  { value: "24", label: "Next 24 Months" },
];

const KINDS = [
  { value: "all", label: "Interest + Principal" },
  { value: "interest", label: "Interest Only" },
];

function Dot({ color }: { color: string }) {
  return (
    <span
      className="size-2 shrink-0 rounded-full"
      style={{ backgroundColor: color }}
      aria-hidden="true"
    />
  );
}

export function InflowsCard() {
  const [count, setCount] = useState<InflowMonthsCount>(12);
  const { state, retry, switching } = useAnalyticsSection<AnalyticsInflows>(inflowsPath(count));

  if (state.status === "loading") {
    return <Skeleton className="h-[420px] rounded-xl" aria-busy="true" aria-label="Loading…" />;
  }

  if (state.status === "error") {
    return (
      <Card size="sm" className="min-w-0 gap-3 px-4">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Money Coming In
        </p>
        <div>
          <p className="text-[13.5px] font-medium text-destructive">{state.message}</p>
          {state.description && (
            <p className="text-[13.5px] text-muted-foreground">{state.description}</p>
          )}
        </div>
        <Button variant="outline" className="self-start" onClick={retry}>
          Retry
        </Button>
      </Card>
    );
  }

  return (
    <InflowsBody
      data={state.data}
      count={count}
      onCountChange={setCount}
      switching={switching}
    />
  );
}

function InflowsBody({
  data,
  count,
  onCountChange,
  switching,
}: {
  data: AnalyticsInflows;
  count: InflowMonthsCount;
  onCountChange: (n: InflowMonthsCount) => void;
  switching: boolean;
}) {
  const [type, setType] = useState("all");
  const [kind, setKind] = useState("all");
  const [picked, setPicked] = useState<string | null>(null);

  const effectiveType = type === "all" || data.types.includes(type) ? type : "all";
  const interestOnly = kind === "interest";
  const months = filterInflows(data.months, effectiveType, interestOnly);
  const totals = inflowTotals(months);
  const columns = inflowColumns(months);
  const fallback = defaultMonth(months);
  const activeMonth = picked && months.some((m) => m.month === picked) ? picked : fallback;
  const activeData = months.find((m) => m.month === activeMonth);
  const items = sortedItems(activeData);
  const total = totals.interest + totals.principal;
  const dense = months.length > 12;

  const typeItems = [
    { value: "all", label: "All Types" },
    ...data.types.map((t) => ({ value: t, label: inflowTypeLabel(t) })),
  ];

  return (
    <Card size="sm" className="relative min-w-0 gap-4 px-4" aria-busy={switching}>
      <TopProgress active={switching} />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Money Coming In
          </p>
          <CardInfo>
            Interest and principal your bonds, fixed deposits and recurring deposits are expected
            to pay in each month. Bond dates are estimated from the coupon frequency and maturity.
            Stocks, mutual funds and other holdings have no scheduled payouts.
          </CardInfo>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            items={typeItems}
            value={effectiveType}
            disabled={switching}
            onValueChange={(v) => setType(v ?? "all")}
          >
            <SelectTrigger size="sm" className="w-[9.5rem] text-xs" aria-label="Asset type">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
              {typeItems.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            items={KINDS}
            value={kind}
            disabled={switching}
            onValueChange={(v) => setKind(v ?? "all")}
          >
            <SelectTrigger size="sm" className="w-[10.5rem] text-xs" aria-label="Amount shown">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
              {KINDS.map((k) => (
                <SelectItem key={k.value} value={k.value}>
                  {k.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            items={PERIODS}
            value={String(count)}
            disabled={switching}
            onValueChange={(v) => onCountChange(v === "24" ? 24 : 12)}
          >
            <SelectTrigger size="sm" className="w-[9.5rem] text-xs" aria-label="Period">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
              {PERIODS.map((p) => (
                <SelectItem key={p.value} value={p.value}>
                  {p.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div
        className={`flex flex-col gap-4 transition-opacity duration-200 ${switching ? "pointer-events-none opacity-50" : ""}`}
      >
      <div>
        <p className="num text-xl font-semibold">{formatINRWhole(Math.round(total))}</p>
        {total > 0 && (
          <p className="text-[13.2px] text-muted-foreground">
            <span className="num text-gain">{formatINRWhole(Math.round(totals.interest))}</span>{" "}
            interest
            {!interestOnly && (
              <>
                {" · "}
                <span className="num text-foreground">
                  {formatINRWhole(Math.round(totals.principal))}
                </span>{" "}
                principal
              </>
            )}
          </p>
        )}
      </div>

      {total <= 0 ? (
        <p className="rounded-lg border border-dashed py-10 text-center text-[13.5px] text-muted-foreground">
          Nothing is due to come in over the next {count} months.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Dot color="var(--gain)" />
              Interest
            </span>
            {!interestOnly && (
              <span className="flex items-center gap-1.5">
                <Dot color={MONEY_COLOR} />
                Principal
              </span>
            )}
          </div>
          <div
            className={`flex ${dense ? "gap-0.5 sm:gap-1" : "gap-1.5"}`}
            onMouseLeave={() => setPicked(null)}
          >
            {columns.map((c, i) => {
              const label = columnLabel(c.month, i === 0);
              const dim = activeMonth !== c.month ? "opacity-55" : "opacity-100";
              const showLabel = !dense || i % 2 === 0;
              return (
                <button
                  key={c.month}
                  type="button"
                  onMouseEnter={() => setPicked(c.month)}
                  onClick={() => setPicked(c.month)}
                  onFocus={() => setPicked(c.month)}
                  aria-label={`Show ${monthLabel(c.month)}`}
                  className="flex min-w-0 flex-1 flex-col items-stretch gap-2.5 rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <div
                    className={`relative h-[160px] transition-opacity duration-150 lg:h-[200px] ${dim}`}
                  >
                    <span
                      className="absolute inset-x-0 bottom-0 h-px bg-border/50"
                      aria-hidden="true"
                    />
                    {c.interestPct > 0 && (
                      <span
                        className="absolute inset-x-[15%] rounded-t-[4px]"
                        style={{
                          bottom: `calc(${c.principalPct}% + 1px)`,
                          height: `max(2px, calc(${c.interestPct}% - 2px))`,
                          backgroundColor: "var(--gain)",
                        }}
                        aria-hidden="true"
                      />
                    )}
                    {c.principalPct > 0 && !interestOnly && (
                      <span
                        className="absolute inset-x-[15%] rounded-t-[4px]"
                        style={{
                          bottom: "1px",
                          height: `max(2px, calc(${c.principalPct}% - 2px))`,
                          backgroundColor: MONEY_COLOR,
                        }}
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  <span className="flex h-6 flex-col items-center text-[10.5px] leading-tight text-muted-foreground">
                    {showLabel && <span>{label.month}</span>}
                    {showLabel && label.year !== null && (
                      <span className="num opacity-70">{label.year}</span>
                    )}
                  </span>
                </button>
              );
            })}
          </div>

          {activeData && (
            <div className="flex flex-col gap-2 border-t border-border/50 pt-3" aria-live="polite">
              <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[13.5px]">
                <span className="font-medium">{monthLabel(activeData.month)}</span>
                <span className="num">
                  {formatINRWhole(Math.round(activeData.interest + activeData.principal))}
                </span>
              </div>
              {items.length === 0 ? (
                <p className="text-[13.2px] text-muted-foreground">Nothing is due this month.</p>
              ) : (
                <ul className="flex flex-col">
                  {items.map((it) => (
                    <li key={`${it.type}-${it.id}-${it.date}-${it.kind}`}>
                      <Link
                        href={inflowHref(it)}
                        className="flex items-center justify-between gap-3 rounded-md px-1 py-1.5 text-[13.5px] hover:bg-muted/50"
                      >
                        <span className="min-w-0">
                          <span className="block truncate">{it.name}</span>
                          <span className="block text-[13.2px] text-muted-foreground">
                            <span className="num">{formatDate(it.date)}</span>
                            {" · "}
                            {inflowTypeLabel(it.type)}
                            {" · "}
                            {inflowKindLabel(it.kind)}
                          </span>
                        </span>
                        <span className="num shrink-0">
                          {inflowAmountText(
                            it.kind,
                            formatINRWhole(Math.round(interestOnly ? it.interest : itemTotal(it))),
                          )}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
      </div>
    </Card>
  );
}
