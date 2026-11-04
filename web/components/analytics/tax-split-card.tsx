"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatINRWhole } from "@/lib/format";
import { MONEY_COLOR } from "@/lib/growth";
import { taxableShare } from "@/lib/tax";
import type { AnalyticsTax, TaxFreeItem } from "@/lib/types";

const TAX_FREE_COLOR = "oklch(0.72 0.12 160)";

function itemHref(item: TaxFreeItem): string {
  return item.kind === "tax_free_bond" ? `/portfolio/bond/${item.id}` : `/portfolio/pf/${item.id}`;
}

export function TaxSplitCard({ tax }: { tax: AnalyticsTax }) {
  const [open, setOpen] = useState(false);
  const taxable = tax.taxable.interest_projected;
  const taxFree = tax.tax_free.interest_projected;
  const total = taxable + taxFree;
  const share = taxableShare(taxable, taxFree);
  const items = tax.tax_free.items;
  const canOpen = items.length > 0;

  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <div className="flex items-center gap-1.5">
        <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Taxable Or Tax-Free
        </p>
        <CardInfo>
          Taxable interest is added to your income and taxed at your slab. PPF, EPF, VPF and
          tax-free bond interest is not taxed. For EPF, interest on your own contributions above
          ₹2.5 lakh a year is taxable; that is not worked out here.
        </CardInfo>
      </div>

      <div>
        <p className="num text-xl font-semibold">{formatINRWhole(total)}</p>
        <p className="text-[13.2px] text-muted-foreground">
          {tax.is_current ? "Expected by 31 Mar" : "Full year"}
        </p>
      </div>

      {total > 0 ? (
        <div
          className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted"
          aria-hidden="true"
        >
          <span
            className="block h-full rounded-full"
            style={{ width: `${share}%`, backgroundColor: MONEY_COLOR }}
          />
          <span
            className="block h-full flex-1 rounded-full"
            style={{ backgroundColor: TAX_FREE_COLOR }}
          />
        </div>
      ) : (
        <p className="py-2 text-center text-xs text-muted-foreground">No interest in this year.</p>
      )}

      <ul className="flex flex-col gap-0.5">
        <li className="flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px]">
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ backgroundColor: MONEY_COLOR }}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1 truncate">Taxable</span>
          <span className="num shrink-0 text-right">{formatINRWhole(taxable)}</span>
        </li>
        <li className="min-w-0">
          <button
            type="button"
            aria-expanded={open}
            disabled={!canOpen}
            onClick={() => setOpen(!open)}
            className="flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left text-[13.5px] outline-none transition-colors enabled:hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
          >
            <span
              className="size-2 shrink-0 rounded-full"
              style={{ backgroundColor: TAX_FREE_COLOR }}
              aria-hidden="true"
            />
            <span className="min-w-0 flex-1 truncate">Tax-free</span>
            <span className="num shrink-0 text-right">{formatINRWhole(taxFree)}</span>
            {canOpen && (
              <ChevronDown
                className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${open ? "" : "-rotate-90"}`}
                aria-hidden="true"
              />
            )}
          </button>
          {open && canOpen && (
            <ul className="mb-1 ml-6 flex flex-col border-l border-border/50 pl-2">
              {items.map((it) => (
                <li key={`${it.kind}-${it.id}`} className="min-w-0">
                  <Link
                    href={itemHref(it)}
                    className="flex items-center gap-2 rounded-md px-1.5 py-1 text-[13.2px] outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="min-w-0 flex-1 truncate" title={it.name}>
                      {it.name}
                    </span>
                    <span className="num shrink-0 text-muted-foreground">
                      {formatINRWhole(it.interest_projected)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </li>
      </ul>
    </Card>
  );
}
