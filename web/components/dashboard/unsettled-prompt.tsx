"use client";

import { useState } from "react";
import Link from "next/link";
import { BellRing, ChevronDown } from "lucide-react";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { getAssetEntry } from "@/lib/asset-catalog";
import { formatINR } from "@/lib/format";
import type { Unsettled } from "@/lib/types";
import {
  maturedOnText,
  settleHref,
  unsettledTitle,
  unsettledToggleLabel,
  visibleUnsettled,
} from "@/lib/unsettled";
import { cn } from "@/lib/utils";

/** Matured deposits and bonds whose payout is not recorded yet. Hidden when there are none. */
export function UnsettledPrompt({ unsettled }: { unsettled: Unsettled }) {
  const [expanded, setExpanded] = useState(false);
  if (unsettled.count === 0) return null;

  const rows = visibleUnsettled(unsettled.items, expanded);
  const toggle = unsettledToggleLabel(unsettled.items.length, expanded);

  return (
    <Card
      size="sm"
      className="min-w-0 gap-3 border border-primary/40 bg-primary/[0.04] px-4"
    >
      <div className="flex items-start gap-3">
        <span
          className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary"
          aria-hidden="true"
        >
          <BellRing className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="num text-[15.4px] font-medium">
            {unsettledTitle(unsettled.count, unsettled.amount)}
          </p>
          <p className="text-[13.2px] text-muted-foreground">
            This money left your totals. Tell us where it went.
          </p>
        </div>
      </div>
      <ul className="flex flex-col divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60 bg-card">
        {rows.map((item) => {
          const entry = getAssetEntry(item.type);
          return (
            <li
              key={`${item.type}-${item.id}`}
              className="flex items-center gap-3 px-3 py-2.5 text-[13.5px]"
            >
              {entry ? <AssetTypeIcon icon={entry.icon} /> : null}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.name}</span>
                <span className="num block truncate text-xs text-muted-foreground">
                  {maturedOnText(item.maturity_date)}
                </span>
              </span>
              <span className="num shrink-0 text-right">
                {formatINR(item.amount)}
              </span>
              <Link
                href={settleHref(item)}
                className={buttonVariants({ size: "sm" })}
                aria-label={`Settle ${item.name}`}
              >
                Settle
              </Link>
            </li>
          );
        })}
      </ul>
      {toggle ? (
        <button
          type="button"
          onClick={() => setExpanded((o) => !o)}
          aria-expanded={expanded}
          className="flex w-fit items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {toggle}
          <ChevronDown
            className={cn(
              "size-3.5 transition-transform",
              expanded && "rotate-180",
            )}
            aria-hidden="true"
          />
        </button>
      ) : null}
    </Card>
  );
}
