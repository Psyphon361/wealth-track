"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { ChevronDown, TriangleAlertIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { getAssetEntry } from "@/lib/asset-catalog";
import { formatDate, formatINRWhole } from "@/lib/format";
import {
  flagText,
  heldBetween,
  saleTermSummary,
  sourceText,
  termText,
  type CapitalGains,
  type CapitalGainsSale,
} from "@/lib/capital-gains";
import { TopProgress } from "./top-progress";
import { gainClass } from "./gains-summary";

const PAGE = 10;
const ROW_FOCUS =
  "outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring";
const EXPAND_IN =
  "motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-top-1 motion-safe:duration-200";

function Chevron({ open }: { open: boolean }) {
  return (
    <ChevronDown
      className={`size-3.5 shrink-0 text-muted-foreground motion-safe:transition-transform ${open ? "" : "-rotate-90"}`}
      aria-hidden="true"
    />
  );
}

export function saleKey(s: CapitalGainsSale): string {
  return s.exit_id !== null ? `e${s.exit_id}` : `${s.source}-${s.holding_id}-${s.sold_on}`;
}

export function SaleRow({ sale }: { sale: CapitalGainsSale }) {
  const [open, setOpen] = useState(false);
  const typeLabel = getAssetEntry(sale.asset_type)?.title ?? sale.asset_type;
  const flagged = sale.flags.length > 0;

  return (
    <li className="min-w-0">
      <div className="flex items-start gap-1">
        <button
          type="button"
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} details for ${sale.name}`}
          onClick={() => setOpen(!open)}
          className={`mt-1.5 shrink-0 rounded-md p-1 ${ROW_FOCUS}`}
        >
          <Chevron open={open} />
        </button>
        <div className="grid min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 py-1.5 text-[13.5px]">
          <span className="flex min-w-0 items-center gap-1.5">
            <Link
              href={`/portfolio/${sale.asset_type}/${sale.holding_id}`}
              className="min-w-0 truncate hover:underline"
              title={sale.name}
            >
              {sale.name}
            </Link>
            {flagged && (
              <TriangleAlertIcon
                className="size-3.5 shrink-0 text-amber-400"
                aria-label="Needs a look"
              />
            )}
          </span>
          <span className={`num text-right font-medium ${gainClass(sale.gain)}`}>
            {sale.estimated && "≈ "}
            {formatINRWhole(sale.gain)}
          </span>
          <span className="min-w-0 text-[13.2px] text-muted-foreground">
            {typeLabel} · {sale.estimated ? sourceText(sale.source) : "Sold"}{" "}
            {formatDate(sale.sold_on)} · {saleTermSummary(sale)}
            {sale.estimated && (
              <span className="ml-1.5 rounded-sm bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                Estimated
              </span>
            )}
          </span>
          <span className="num text-right text-[13.2px] text-muted-foreground">
            {sale.estimated && "≈ "}
            {formatINRWhole(sale.proceeds)} for {formatINRWhole(sale.cost)}
          </span>
        </div>
      </div>

      {open && (
        <div className={`mb-2 ml-6 border-l border-border/50 pl-3 ${EXPAND_IN}`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[480px] text-[13.2px]">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wider text-muted-foreground">
                  <th className="py-1 pr-3 font-medium">Bought On</th>
                  <th className="py-1 pr-3 font-medium">Held</th>
                  <th className="py-1 pr-3 text-right font-medium">Quantity</th>
                  <th className="py-1 pr-3 text-right font-medium">Cost</th>
                  <th className="py-1 pr-3 text-right font-medium">Proceeds</th>
                  <th className="py-1 pr-3 text-right font-medium">Gain</th>
                  <th className="py-1 font-medium">Term</th>
                </tr>
              </thead>
              <tbody>
                {sale.lots.map((l, i) => (
                  <Fragment key={i}>
                    <tr>
                      <td className="py-1 pr-3">{l.bought_on ? formatDate(l.bought_on) : "Unknown"}</td>
                      <td className="py-1 pr-3">{heldBetween(l.bought_on, sale.sold_on)}</td>
                      <td className="num py-1 pr-3 text-right">{l.quantity ?? "—"}</td>
                      <td className="num py-1 pr-3 text-right">{formatINRWhole(l.cost)}</td>
                      <td className="num py-1 pr-3 text-right">{formatINRWhole(l.proceeds)}</td>
                      <td className={`num py-1 pr-3 text-right ${gainClass(l.gain)}`}>
                        {formatINRWhole(l.gain)}
                      </td>
                      <td className="py-1">{termText(l.term)}</td>
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {flagged && (
            <ul className="mt-1 space-y-1">
              {sale.flags.map((f) => (
                <li key={f} className="flex items-start gap-1.5 text-[13.2px] text-amber-400">
                  <TriangleAlertIcon className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                  <span>{flagText(f)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

export function GainsSalesCard({
  data,
  switching,
}: {
  data: CapitalGains;
  switching: boolean;
}) {
  const [shown, setShown] = useState(PAGE);
  const sales = [...data.sales].sort((a, b) =>
    a.sold_on < b.sold_on ? 1 : a.sold_on > b.sold_on ? -1 : (b.exit_id ?? 0) - (a.exit_id ?? 0),
  );
  const visible = sales.slice(0, shown);

  return (
    <Card size="sm" className="relative min-w-0 gap-3 px-4">
      <TopProgress active={switching} />
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Sales
        </p>
        <CardInfo>
          Everything you sold in this financial year, newest first. Open a sale to see each
          purchase it came from.
        </CardInfo>
      </div>
      <ul
        aria-busy={switching}
        className={`flex flex-col divide-y divide-border/40 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        {visible.map((s) => (
          <SaleRow key={saleKey(s)} sale={s} />
        ))}
      </ul>
      {sales.length > PAGE && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="w-full text-muted-foreground"
          onClick={() => setShown(shown < sales.length ? Math.min(sales.length, shown + PAGE) : PAGE)}
        >
          {shown < sales.length ? "Show more" : "Show less"}
        </Button>
      )}
    </Card>
  );
}
