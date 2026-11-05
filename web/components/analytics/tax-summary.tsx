"use client";

import { Card } from "@/components/ui/card";
import { TopProgress } from "./top-progress";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import { leftToPay, leftToPayLabel } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

function Figure({
  label,
  children,
  subline,
}: {
  label: string;
  children: React.ReactNode;
  subline?: React.ReactNode;
}) {
  return (
    <div className="min-w-0 sm:text-center">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-0.5">{children}</div>
      {subline && <p className="text-[13.2px] text-muted-foreground">{subline}</p>}
    </div>
  );
}

export function TaxSummary({
  tax,
  switching,
  slab,
}: {
  tax: AnalyticsTax;
  switching: boolean;
  slab: number | null;
}) {
  const taxable = tax.taxable.interest_projected;
  const tds = tax.totals.tds_estimate;
  const left = slab === null ? null : leftToPay(taxable, tds, slab);
  const taxFree = tax.tax_free.interest_projected;

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Interest &amp; TDS
        </p>
        <CardInfo>
          Interest your FDs, RDs, bonds and savings pay in the financial year (1 April to 31
          March). Banks deduct TDS once one payer&apos;s interest passes its limit; corporate bonds
          deduct it on every coupon. Left to pay is the tax at your slab rate plus 4% cess
          (surcharge not included), minus the TDS already deducted. Your slab is saved in this
          browser only and never sent to the server.
        </CardInfo>
      </div>

      <div
        aria-busy={switching}
        className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <div className="grid gap-3 sm:grid-cols-3 sm:gap-0">
          <div className="sm:pr-4">
            <Figure
              label="Taxable interest"
              subline={tax.is_current ? `${formatINRWhole(tax.taxable.interest_to_date)} so far` : "Full year"}
            >
              <p className="num text-2xl font-semibold">{formatINRWhole(taxable)}</p>
            </Figure>
          </div>
          <div className="border-t border-border/50 pt-3 sm:border-l sm:border-t-0 sm:px-4 sm:pt-0">
            <Figure label="TDS deducted" subline="by banks and issuers">
              <p className="num text-2xl font-semibold">{formatINRWhole(tds)}</p>
            </Figure>
          </div>
          <div className="border-t border-border/50 pt-3 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
            <Figure
              label={leftToPayLabel(left)}
              subline={
                left === null
                  ? undefined
                  : left < 0
                    ? "when you file"
                    : left === 0
                      ? "TDS covers it"
                      : `at ${slab}% with cess`
              }
            >
              {left === null ? (
                <p className="text-[13.5px] text-muted-foreground">Pick your slab</p>
              ) : (
                <p className={`num text-2xl font-semibold ${left > 0 ? "text-amber-300" : left < 0 ? "text-gain" : ""}`}>
                  {formatINRWhole(Math.abs(left))}
                </p>
              )}
            </Figure>
          </div>
        </div>

        {taxFree > 0 && (
          <p className="text-[13.2px] text-muted-foreground">
            Plus {formatINRWhole(taxFree)} tax-free (PPF, EPF, tax-free bonds)
          </p>
        )}
      </div>
    </Card>
  );
}
