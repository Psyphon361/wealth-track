"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ANALYTICS_TAX_PATH } from "@/lib/analytics";
import { BONDS_NOTE, SAVINGS_80TTA_NOTE, savingsSentence } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";
import { TaxInterestCard } from "./tax-interest-card";
import { TaxTdsCard } from "./tax-tds-card";
import { useAnalyticsSection } from "./use-analytics-section";

export function Tax() {
  const [fy, setFy] = useState<number | null>(null);
  const path = fy === null ? ANALYTICS_TAX_PATH : `${ANALYTICS_TAX_PATH}?fy=${fy}`;
  const { state, retry, switching } = useAnalyticsSection<AnalyticsTax>(path);

  if (state.status === "loading") {
    return (
      <div className="grid items-start gap-3 lg:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} aria-busy="true" aria-label="Loading…">
            <Skeleton className="h-[360px] rounded-xl" />
          </div>
        ))}
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
      <div className="grid items-start gap-3 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-3">
          <TaxInterestCard tax={tax} switching={switching} onFyChange={setFy} />
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          <TaxTdsCard tax={tax} />
        </div>
      </div>

      <div className="space-y-0.5">
        {tax.savings && (
          <p className="text-xs text-muted-foreground">
            {savingsSentence(tax.savings)} {SAVINGS_80TTA_NOTE}
          </p>
        )}
        {tax.excluded.bonds > 0 && <p className="text-xs text-muted-foreground">{BONDS_NOTE}</p>}
      </div>
    </div>
  );
}
