"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatINRWhole } from "@/lib/format";
import { SLAB_OPTIONS, TAX_SLAB_KEY, parseSlab, slabSentence, taxOnInterest } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

const ITEMS = SLAB_OPTIONS.map((s) => ({ value: String(s), label: `${s}%` }));

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

export function TaxSlabCard({ tax, switching }: { tax: AnalyticsTax; switching: boolean }) {
  const [slab, setSlab] = useState<number | null>(null);

  useEffect(() => {
    // Read after mount so server and first client render match.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSlab(readSlab());
  }, []);

  const taxable = tax.taxable.interest_projected;
  const tds = tax.totals.tds_estimate;
  const taxAmount = slab === null ? null : taxOnInterest(taxable, slab);

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4" aria-busy={switching}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Tax on your interest
          </p>
          <CardInfo>
            Taxable interest times your slab rate, plus 4% cess. Surcharge is not included. Your
            slab is saved in this browser only and never sent to the server.
          </CardInfo>
        </div>
        <Select
          items={ITEMS}
          value={slab === null ? null : String(slab)}
          disabled={switching}
          onValueChange={(v) => {
            const n = parseSlab(v as string | null);
            if (n === null) return;
            setSlab(n);
            writeSlab(n);
          }}
        >
          <SelectTrigger size="sm" className="w-[8.5rem] text-xs" aria-label="Your Tax Slab">
            <SelectValue placeholder="Your Tax Slab" />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
            {ITEMS.map((i) => (
              <SelectItem key={i.value} value={i.value}>
                {i.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {slab === null || taxAmount === null ? (
        <p className="text-[13.5px] text-muted-foreground">
          Pick your tax slab to see the tax on your interest.
        </p>
      ) : (
        <>
          <div>
            <p className="num text-xl font-semibold">{formatINRWhole(taxAmount)}</p>
            <p className="text-[13.2px] text-muted-foreground">
              {tax.is_current ? "Expected by 31 Mar" : "Full year"}
            </p>
          </div>
          <p className="text-[13.5px] text-foreground">
            {slabSentence(taxable, tds, slab, tax.is_current)}
          </p>
        </>
      )}
    </Card>
  );
}
