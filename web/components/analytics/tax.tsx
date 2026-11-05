"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYTICS_TAX_PATH } from "@/lib/analytics";
import { TAX_SLAB_KEY, bondsNote, parseSlab, savingsSentence } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";
import { BondSchedule } from "./bond-schedule";
import { TaxSummary } from "./tax-summary";
import { TaxTable } from "./tax-table";
import { TaxToolbar } from "./tax-toolbar";
import { useAnalyticsSection } from "./use-analytics-section";

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

export function Tax() {
  const [fy, setFy] = useState<number | null>(null);
  const path = fy === null ? ANALYTICS_TAX_PATH : `${ANALYTICS_TAX_PATH}?fy=${fy}`;
  const { state, retry, switching } = useAnalyticsSection<AnalyticsTax>(path);
  const [slab, setSlab] = useState<number | null>(null);

  useEffect(() => {
    // Read after mount so server and first client render match.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSlab(readSlab());
  }, []);

  if (state.status === "loading") {
    return (
      <div className="space-y-3" aria-busy="true" aria-label="Loading…">
        <Skeleton className="h-[200px] rounded-xl" />
        <div className="flex flex-col gap-3 sm:flex-row">
          <Skeleton className="h-14 w-full sm:w-48" />
          <Skeleton className="h-14 w-full sm:w-56" />
        </div>
        <Skeleton className="h-[110px] rounded-xl" />
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

  const tax = state.data;

  return (
    <div className="space-y-3">
      <BondSchedule />
      <TaxToolbar
        tax={tax}
        switching={switching}
        slab={slab}
        onFyChange={setFy}
        onSlabChange={(n) => {
          setSlab(n);
          writeSlab(n);
        }}
      />
      <TaxSummary tax={tax} switching={switching} slab={slab} />
      <div className="min-w-0">
        <TaxTable tax={tax} switching={switching} />
      </div>

      <div className="space-y-0.5">
        {tax.savings && (
          <p className="text-xs text-muted-foreground">{savingsSentence(tax.savings)}</p>
        )}
        {tax.excluded.bonds > 0 && (
          <p className="text-xs text-muted-foreground">{bondsNote(tax.excluded.bonds)}</p>
        )}
      </div>
    </div>
  );
}
