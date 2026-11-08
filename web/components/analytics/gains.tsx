"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { Loader2Icon } from "lucide-react";
import { CardInfo } from "@/components/analytics/card-info";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate, formatINRWhole } from "@/lib/format";
import { capitalGainsPath, footnotes, type CapitalGains } from "@/lib/capital-gains";
import {
  SLAB_OPTIONS,
  TAX_SLAB_KEY,
  fyDisplay,
  parseSlab,
  slabOptionLabel,
  slabTriggerLabel,
} from "@/lib/tax";
import { GainsBondInterest } from "./gains-bond-interest";
import { GainsExpectedCard } from "./gains-expected-card";
import { GainsBucketsCard } from "./gains-buckets-card";
import { GainsSalesCard } from "./gains-sales-card";
import { GainsSummary } from "./gains-summary";
import { TOOLBAR_LABEL_CLS } from "./tax-toolbar";
import { useAnalyticsSection } from "./use-analytics-section";

const SLAB_ITEMS = SLAB_OPTIONS.map((s) => ({ value: String(s), label: slabOptionLabel(s) }));

function readSlab(): number | null {
  try {
    return parseSlab(window.localStorage.getItem(TAX_SLAB_KEY));
  } catch {
    return null;
  }
}

function writeSlab(slab: number) {
  try {
    window.localStorage.setItem(TAX_SLAB_KEY, String(slab));
  } catch {
    // storage unavailable; the slab just won't be remembered
  }
}

function GainsToolbar({
  data,
  switching,
  slab,
  onFyChange,
  onSlabChange,
}: {
  data: CapitalGains;
  switching: boolean;
  slab: number | null;
  onFyChange: (startYear: number) => void;
  onSlabChange: (slab: number) => void;
}) {
  const fyLabelId = useId();
  const slabLabelId = useId();
  const fyItems = data.available_fys.map((o) => ({
    value: String(o.start_year),
    label: `FY ${fyDisplay(o.label)}`,
    current: o.is_current,
  }));
  const currentFy = data.available_fys.find((o) => o.label === data.fy);

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      {fyItems.length > 0 && (
        <div className="flex w-full flex-col gap-1 sm:w-48">
          <span id={fyLabelId} className={TOOLBAR_LABEL_CLS}>
            Financial Year
          </span>
          <Select
            items={fyItems}
            value={currentFy ? String(currentFy.start_year) : null}
            disabled={switching}
            onValueChange={(v) => {
              if (v) onFyChange(Number(v));
            }}
          >
            <SelectTrigger size="sm" className="w-full text-xs" aria-labelledby={fyLabelId}>
              <span className="flex min-w-0 items-center gap-1.5">
                <SelectValue />
                {switching && (
                  <Loader2Icon
                    className="size-3.5 shrink-0 animate-spin text-muted-foreground motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                )}
              </span>
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
              {fyItems.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                  {i.current && <span className="text-muted-foreground"> Current</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="flex w-full flex-col gap-1 sm:w-56">
        <div className="flex items-center gap-1.5">
          <span id={slabLabelId} className={TOOLBAR_LABEL_CLS}>
            Your Income Tax Slab
          </span>
          <CardInfo>Used only to estimate tax on gains taxed at your slab. Stays in this browser.</CardInfo>
        </div>
        <Select
          items={SLAB_ITEMS}
          value={slab === null ? null : String(slab)}
          disabled={switching}
          onValueChange={(v) => {
            const n = parseSlab(v as string | null);
            if (n !== null) onSlabChange(n);
          }}
        >
          <SelectTrigger size="sm" className="w-full text-xs" aria-labelledby={slabLabelId}>
            <SelectValue placeholder="Choose your slab">
              {(v: string | null) => {
                const n = parseSlab(v);
                return n === null ? "Choose your slab" : slabTriggerLabel(n);
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
            {SLAB_ITEMS.map((i) => (
              <SelectItem key={i.value} value={i.value}>
                {i.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}

export function Gains() {
  const [fy, setFy] = useState<number | null>(null);
  const { state, retry, switching } = useAnalyticsSection<CapitalGains>(capitalGainsPath(fy));
  const [slab, setSlab] = useState<number | null>(null);

  useEffect(() => {
    // Read after mount so server and first client render match.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSlab(readSlab());
  }, []);

  if (state.status === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading…">
        <div className="flex flex-col gap-3 sm:flex-row">
          <Skeleton className="h-14 w-full sm:w-48" />
          <Skeleton className="h-14 w-full sm:w-56" />
        </div>
        <Skeleton className="h-[140px] rounded-xl" />
        <Skeleton className="h-[260px] rounded-xl" />
        <Skeleton className="h-[260px] rounded-xl" />
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
  const empty =
    data.sales.length === 0 &&
    data.expected.length === 0 &&
    data.summary.sales_count === 0 &&
    data.tax_free.items.length === 0;

  return (
    <div className="space-y-3">
      <GainsToolbar
        data={data}
        switching={switching}
        slab={slab}
        onFyChange={setFy}
        onSlabChange={(n) => {
          setSlab(n);
          writeSlab(n);
        }}
      />

      {empty ? (
        <Card size="sm" className="relative min-w-0 gap-1 px-4">
          <p className="text-[15.4px] font-medium">No sales in FY {fyDisplay(data.fy)}</p>
          <p className="text-[13.2px] text-muted-foreground">
            Sales you record with Sell show up here.
          </p>
        </Card>
      ) : (
        <>
          <GainsSummary data={data} switching={switching} slab={slab} />
          {data.bond_interest && data.bond_interest.holdings_count > 0 && (
            <GainsBondInterest interest={data.bond_interest} slab={slab} switching={switching} />
          )}
          <div className="min-w-0">
            <GainsBucketsCard data={data} switching={switching} />
          </div>
          {data.sales.length > 0 && (
            <div className="min-w-0">
              <GainsSalesCard key={data.fy} data={data} switching={switching} />
            </div>
          )}
          {data.expected.length > 0 && (
            <div className="min-w-0">
              <GainsExpectedCard data={data} switching={switching} />
            </div>
          )}
          {data.tax_free.items.length > 0 && (
            <Card size="sm" className="min-w-0 gap-2 px-4">
              <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Tax-Free: Sovereign Gold Bond Redemptions
              </p>
              <ul className="flex flex-col divide-y divide-border/40">
                {data.tax_free.items.map((t) => (
                  <li
                    key={t.exit_id ?? `${t.holding_id}-${t.settled_on}`}
                    className="flex items-center justify-between gap-3 py-1.5 text-[13.5px]"
                  >
                    <span className="min-w-0">
                      <Link
                        href={`/portfolio/bond/${t.holding_id}`}
                        className="block truncate hover:underline"
                        title={t.name}
                      >
                        {t.name}
                      </Link>
                      <span className="text-[13.2px] text-muted-foreground">
                        Redeemed {formatDate(t.settled_on)}
                        {t.estimated && (
                          <span className="ml-1.5 rounded-sm bg-muted px-1.5 py-0.5 text-[11px]">
                            Estimated
                          </span>
                        )}
                      </span>
                    </span>
                    <span className="num shrink-0 text-right">
                      {t.estimated && "≈ "}
                      {formatINRWhole(t.amount)}
                      <span className="block text-[13.2px] text-muted-foreground">
                        Cost {formatINRWhole(t.cost)}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      <div className="space-y-0.5">
        {footnotes(data).map((n) => (
          <p key={n} className="text-xs text-muted-foreground">
            {n}
          </p>
        ))}
        <p className="text-xs text-muted-foreground">Estimates only; check with your tax filing.</p>
      </div>
    </div>
  );
}
