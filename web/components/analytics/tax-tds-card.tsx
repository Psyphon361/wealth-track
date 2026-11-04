import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import { tdsSentence } from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

export function TaxTdsCard({ tax }: { tax: AnalyticsTax }) {
  const crossing = tax.payers.filter((p) => p.crosses);

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          TDS to expect
        </p>
        <CardInfo>
          A bank deducts 10% TDS on a whole year&apos;s interest once it passes ₹50,000 (₹10,000
          for finance companies and listed bond issuers). Government bonds and SGBs have no TDS.
          This assumes you have given your PAN. TDS is not an extra tax: you can claim it back in
          your tax return.
        </CardInfo>
      </div>

      <div>
        <p className="num text-xl font-semibold">{formatINRWhole(tax.totals.tds_estimate)}</p>
        <p className="text-[13.5px] text-foreground">{tdsSentence(tax.payers, tax.is_current)}</p>
      </div>

      {crossing.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {crossing.map((p) => (
            <li
              key={p.key}
              className="flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px]"
            >
              <span className="min-w-0 flex-1">
                <span className="block truncate" title={p.name}>
                  {p.name}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  On {formatINRWhole(p.interest_projected)} of interest
                </span>
              </span>
              <span className="num shrink-0 text-right text-loss">
                {formatINRWhole(p.tds_estimate)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
