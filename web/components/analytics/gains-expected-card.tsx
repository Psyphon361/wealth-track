"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatDate, formatINRWhole } from "@/lib/format";
import { saleTermSummary, sourceText, type CapitalGains } from "@/lib/capital-gains";
import { TopProgress } from "./top-progress";
import { gainClass } from "./gains-summary";
import { saleKey } from "./gains-sales-card";

export function GainsExpectedCard({
  data,
  switching,
}: {
  data: CapitalGains;
  switching: boolean;
}) {
  const rows = [...data.expected].sort((a, b) => (a.sold_on < b.sold_on ? -1 : a.sold_on > b.sold_on ? 1 : 0));

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Expected Later This Year
        </p>
        <CardInfo>
          Bonds due to be repaid, or planned to be sold, before the financial year ends. These are
          estimates at face value.
        </CardInfo>
      </div>
      <div
        aria-busy={switching}
        className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <div>
          <p className={`num text-2xl font-semibold ${gainClass(data.expected_gain)}`}>
            ≈ {formatINRWhole(data.expected_gain)}
          </p>
          <p className="text-[13.2px] text-muted-foreground">
            Not in the totals until the date passes.
          </p>
        </div>
        <ul className="flex flex-col divide-y divide-border/40">
          {rows.map((s) => (
            <li
              key={saleKey(s)}
              className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-1.5 text-[13.5px]"
            >
              <Link
                href={`/portfolio/${s.asset_type}/${s.holding_id}`}
                className="min-w-0 truncate hover:underline"
                title={s.name}
              >
                {s.name}
              </Link>
              <span className={`num text-right font-medium ${gainClass(s.gain)}`}>
                ≈ {formatINRWhole(s.gain)}
              </span>
              <span className="min-w-0 text-[13.2px] text-muted-foreground">
                {sourceText(s.source)} · {formatDate(s.sold_on)}
              </span>
              <span className="text-right text-[13.2px] text-muted-foreground">
                {saleTermSummary(s)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
