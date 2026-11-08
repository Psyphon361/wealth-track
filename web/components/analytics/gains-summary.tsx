"use client";

import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import { estimatedTax, type CapitalGains } from "@/lib/capital-gains";
import { TopProgress } from "./top-progress";

export function gainClass(n: number): string {
  return n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
}

function Figure({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 sm:text-center">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}

export function GainsSummary({
  data,
  switching,
  slab,
}: {
  data: CapitalGains;
  switching: boolean;
  slab: number | null;
}) {
  const s = data.summary;
  const tax = estimatedTax(s, slab);

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Capital Gains
        </p>
        <CardInfo>
          Profit or loss on the stocks, bonds, mutual funds and gold you sold in the financial year
          (1 April to 31 March). Short term and long term are taxed at different rates. Your slab is
          saved in this browser only and never sent to the server.
        </CardInfo>
      </div>

      <div
        aria-busy={switching}
        className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <div className="grid gap-3 sm:grid-cols-3 sm:gap-0">
          <div className="sm:pr-4">
            <Figure label="Short-Term Gains">
              <p className={`num text-2xl font-semibold ${gainClass(s.short_term_net)}`}>
                {formatINRWhole(s.short_term_net)}
              </p>
            </Figure>
          </div>
          <div className="border-t border-border/50 pt-3 sm:border-l sm:border-t-0 sm:px-4 sm:pt-0">
            <Figure label="Long-Term Gains">
              <p className={`num text-2xl font-semibold ${gainClass(s.long_term_net)}`}>
                {formatINRWhole(s.long_term_net)}
              </p>
            </Figure>
          </div>
          <div className="border-t border-border/50 pt-3 sm:border-l sm:border-t-0 sm:pl-4 sm:pt-0">
            <Figure label="Estimated Tax">
              {tax === null ? (
                <p className="text-[13.5px] text-muted-foreground">Pick your slab</p>
              ) : (
                <p className={`num text-2xl font-semibold ${tax > 0 ? "text-amber-300" : ""}`}>
                  {formatINRWhole(tax)}
                </p>
              )}
            </Figure>
          </div>
        </div>

        {(s.exemption_used > 0 || s.losses_set_off > 0) && (
          <div className="text-[13.2px] text-muted-foreground">
            {s.exemption_used > 0 && (
              <p>{formatINRWhole(s.exemption_used)} long-term equity gains exempt</p>
            )}
            {s.losses_set_off > 0 && <p>{formatINRWhole(s.losses_set_off)} of losses set off</p>}
          </div>
        )}
      </div>
    </Card>
  );
}
