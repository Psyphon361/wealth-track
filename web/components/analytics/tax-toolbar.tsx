"use client";

import { useId } from "react";
import { Loader2Icon } from "lucide-react";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { SLAB_OPTIONS, fyOptionLabel, parseSlab, slabOptionLabel, slabTriggerLabel } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

const SLAB_ITEMS = SLAB_OPTIONS.map((s) => ({ value: String(s), label: slabOptionLabel(s) }));
export const TOOLBAR_LABEL_CLS = "text-[11px] font-medium uppercase tracking-wider text-muted-foreground";

export function TaxToolbar({
  tax,
  switching,
  slab,
  onFyChange,
  onSlabChange,
}: {
  tax: AnalyticsTax;
  switching: boolean;
  slab: number | null;
  onFyChange: (startYear: number) => void;
  onSlabChange: (slab: number) => void;
}) {
  const fyLabelId = useId();
  const slabLabelId = useId();

  const fyItems = tax.available_fys.map((o) => ({
    value: String(o.start_year),
    label: fyOptionLabel(o),
    current: o.is_current,
  }));
  const currentFy = tax.available_fys.find((o) => o.label === tax.fy);

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
      {fyItems.length > 0 && (
        <div className="flex w-full flex-col gap-1 sm:w-48">
          <span id={fyLabelId} className={TOOLBAR_LABEL_CLS}>
            Financial year
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
                  {i.current && <span className="text-muted-foreground"> current</span>}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      <div className="flex w-full flex-col gap-1 sm:w-56">
        <div className="flex items-center gap-1.5">
          <span id={slabLabelId} className={TOOLBAR_LABEL_CLS}>
            Your income tax slab
          </span>
          <CardInfo>Used only to estimate tax on this interest. Stays in this browser.</CardInfo>
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
