"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatINRWhole } from "@/lib/format";
import { MONEY_COLOR } from "@/lib/growth";
import { barShare, fyOptionLabel, interestSubline, payerHint } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

export function TaxInterestCard({
  tax,
  switching,
  onFyChange,
}: {
  tax: AnalyticsTax;
  switching: boolean;
  onFyChange: (startYear: number) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const items = tax.available_fys.map((o) => ({
    value: String(o.start_year),
    label: fyOptionLabel(o),
  }));
  const current = tax.available_fys.find((o) => o.label === tax.fy);

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4" aria-busy={switching}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Interest this year
          </p>
          <CardInfo>
            Interest your FDs, RDs and bonds pay in the financial year (1 April to 31 March),
            grouped by bank or issuer. TDS is deducted once one payer&apos;s interest passes its
            limit. The figures assume you add no new deposits.
          </CardInfo>
        </div>
        {items.length > 0 && (
          <Select
            items={items}
            value={current ? String(current.start_year) : null}
            disabled={switching}
            onValueChange={(v) => {
              if (v) onFyChange(Number(v));
            }}
          >
            <SelectTrigger size="sm" className="w-[10.5rem] text-xs" aria-label="Financial year">
              <SelectValue />
            </SelectTrigger>
            <SelectContent alignItemWithTrigger={false} className="w-(--anchor-width) min-w-0">
              {items.map((i) => (
                <SelectItem key={i.value} value={i.value}>
                  {i.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      <div>
        <p className="num text-xl font-semibold">{formatINRWhole(tax.totals.interest_projected)}</p>
        <p className="text-[13.2px] text-muted-foreground">{interestSubline(tax)}</p>
      </div>

      {tax.payers.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">
          No FD, RD or bond interest in this year.
        </p>
      ) : (
        <ul className="flex flex-col gap-0.5">
          {tax.payers.map((p) => {
            const isOpen = open === p.key;
            const share = p.threshold === null ? 0 : barShare(p.interest_projected, p.threshold);
            return (
              <li key={p.key} className="min-w-0">
                <button
                  type="button"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? null : p.key)}
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-[13.5px] outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <ChevronDown
                    className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${isOpen ? "" : "-rotate-90"}`}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={p.name}>
                      {p.name}
                    </span>
                    <span
                      className={`block truncate text-xs ${p.crosses ? "text-loss" : "text-muted-foreground"}`}
                    >
                      {payerHint(p)}
                    </span>
                    {p.threshold !== null && (
                      <span
                        className="mt-1 block h-1 overflow-hidden rounded-full bg-muted"
                        aria-hidden="true"
                      >
                        <span
                          className={`block h-full rounded-full ${p.crosses ? "bg-loss" : ""}`}
                          style={{
                            width: `${share}%`,
                            ...(p.crosses ? {} : { backgroundColor: MONEY_COLOR }),
                          }}
                        />
                      </span>
                    )}
                  </span>
                  <span className="num shrink-0 text-right">
                    {formatINRWhole(p.interest_projected)}
                  </span>
                </button>
                {isOpen && (
                  <ul className="mb-1 ml-6 flex flex-col border-l border-border/50 pl-2">
                    {p.holdings.map((h) => (
                      <li key={`${h.type}-${h.id}`} className="min-w-0">
                        <Link
                          href={`/portfolio/${h.type}/${h.id}`}
                          className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[13.2px] outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <span className="min-w-0 flex-1 truncate" title={h.name}>
                            {h.name}
                          </span>
                          <span className="num shrink-0 text-muted-foreground">
                            {formatINRWhole(h.interest_projected)}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
