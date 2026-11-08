"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { formatINRWhole } from "@/lib/format";
import { bondInterestLeftToPay, type CapitalGainsBondInterest } from "@/lib/capital-gains";
import { leftToPayLabel } from "@/lib/tax";
import { TopProgress } from "./top-progress";

export function GainsBondInterest({
  interest,
  slab,
  switching,
}: {
  interest: CapitalGainsBondInterest;
  slab: number | null;
  switching: boolean;
}) {
  const left = bondInterestLeftToPay(interest, slab);

  return (
    <Card size="sm" className="relative min-w-0 gap-2 px-4">
      <TopProgress active={switching} />
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Bond Interest This Year
      </p>
      <div
        aria-busy={switching}
        className={`flex flex-col gap-1 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <p className="text-[13.5px]">
          <span className="num font-semibold">{formatINRWhole(interest.interest_projected)}</span>{" "}
          in coupons
          <span className="text-muted-foreground">
            {" · "}TDS cut <span className="num">{formatINRWhole(interest.tds_estimate)}</span>
            {" · "}
          </span>
          {left === null ? (
            <span className="text-muted-foreground">Pick your slab</span>
          ) : left < 0 ? (
            <span>
              {leftToPayLabel(left)} <span className="num text-gain">{formatINRWhole(-left)}</span>
            </span>
          ) : (
            <span>
              Left to pay{" "}
              <span className={`num ${left > 0 ? "text-amber-300" : ""}`}>{formatINRWhole(left)}</span>{" "}
              <span className="text-muted-foreground">at your slab</span>
            </span>
          )}
        </p>
        <p className="text-[13.2px] text-muted-foreground">
          Bond interest is taxed at your slab. It is not part of the capital gains above.{" "}
          <Link href="/analytics/interest" className="text-foreground underline-offset-2 hover:underline">
            See Interest &amp; TDS
          </Link>
        </p>
      </div>
    </Card>
  );
}
