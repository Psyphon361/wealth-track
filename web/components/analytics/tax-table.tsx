"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ChevronDown } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { formatDate, formatINR, formatINRWhole } from "@/lib/format";
import { TopProgress } from "./top-progress";
import {
  allClassesProjected,
  classBarPercent,
  classCountText,
  classPayers,
  classProgressText,
  classTdsPill,
  couponsLeft,
  couponsLeftText,
  taxCardLabel,
  tdsLimitMarker,
  tdsSuffix,
} from "@/lib/tax";
import type { AnalyticsTax } from "@/lib/types";

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

function Swatch({ className }: { className: string }) {
  return <span className={`size-2 shrink-0 rounded-full ${className}`} aria-hidden="true" />;
}

export function TaxTable({ tax, switching = false }: { tax: AnalyticsTax; switching?: boolean }) {
  const [openClass, setOpenClass] = useState<string | null>(null);
  const [openPayer, setOpenPayer] = useState<string | null>(null);
  const [openHolding, setOpenHolding] = useState<string | null>(null);
  // Bars start at 0 and grow once the card has mounted; later width changes animate via CSS.
  const [grown, setGrown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setGrown(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const isCurrent = tax.is_current;
  const allProjected = allClassesProjected(tax.by_class);

  return (
    <Card size="sm" className="relative min-w-0 gap-0 px-4">
      <TopProgress active={switching} />
      <div
        aria-busy={switching}
        className={`flex flex-col gap-3 transition-opacity duration-200 ${switching ? "opacity-50" : ""}`}
      >
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {taxCardLabel(tax)}
            </p>
            <CardInfo>
              Interest by asset class, then by bank or issuer. A bank deducts 10% TDS on a whole
              year of interest once it passes ₹50,000 (₹10,000 for finance companies). Corporate
              bonds and NCDs have 10% TDS on every coupon, with no limit. Government bonds, SGBs
              and tax-free bonds have none. This assumes you have given your PAN. TDS is not an
              extra tax: you can claim it back in your tax return. The figures assume you add no
              new deposits.
            </CardInfo>
          </div>
          {isCurrent && tax.by_class.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13.2px] text-muted-foreground">
              <span className="flex items-center gap-1.5">
                <Swatch className="bg-gain" />
                Received so far
              </span>
              <span className="flex items-center gap-1.5">
                <Swatch className="bg-foreground/10" />
                Still to come
              </span>
            </div>
          )}
        </div>

        {tax.by_class.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            No interest in this year.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-border/50">
            {tax.by_class.map((row, i) => {
              const payers = classPayers(tax.payers, row.type);
              const canOpen = payers.length > 0;
              const isOpen = canOpen && openClass === row.type;
              const pct = classBarPercent(row, isCurrent, allProjected);
              const pill = classTdsPill(row, payers);

              const body = (
                <>
                  <span className="flex w-full items-center justify-between gap-3 text-[13.5px]">
                    <span className="flex min-w-0 items-center gap-2">
                      {canOpen ? (
                        <Chevron open={isOpen} />
                      ) : (
                        <span className="size-3.5 shrink-0" aria-hidden="true" />
                      )}
                      <span className="min-w-0 truncate">
                        {row.label}
                        <span className="text-muted-foreground">{classCountText(row)}</span>
                      </span>
                    </span>
                    <span className="num shrink-0 font-medium">
                      {formatINRWhole(row.interest_projected)}
                    </span>
                  </span>
                  <span
                    className="block h-1.5 w-full overflow-hidden rounded-full bg-foreground/10"
                    aria-hidden="true"
                  >
                    <span
                      className="block h-full rounded-full bg-gain motion-safe:transition-[width] motion-safe:duration-500 motion-safe:ease-out"
                      style={{ width: grown ? `${pct}%` : "0%", transitionDelay: `${i * 60}ms` }}
                    />
                  </span>
                  <span className="flex w-full flex-wrap items-center justify-between gap-x-3 gap-y-1.5 text-[13.2px] text-muted-foreground">
                    <span>{classProgressText(row, isCurrent, allProjected)}</span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs ${
                        pill.warn ? "bg-amber-500/15 text-amber-300" : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {pill.text}
                    </span>
                  </span>
                </>
              );
              const cls = `flex w-full flex-col gap-1.5 rounded-md px-1.5 py-2.5 text-left ${ROW_FOCUS}`;

              return (
                <li key={row.type} className="min-w-0">
                  {canOpen ? (
                    <button
                      type="button"
                      aria-expanded={isOpen}
                      onClick={() => setOpenClass(isOpen ? null : row.type)}
                      className={cls}
                    >
                      {body}
                    </button>
                  ) : (
                    <div className={`${cls} hover:bg-transparent`}>{body}</div>
                  )}

                  {isOpen && (
                    <ul className={`mb-2 ml-4 flex flex-col border-l border-border/50 pl-2 ${EXPAND_IN}`}>
                      {payers.map((p) => {
                        const pKey = `${row.type}:${p.key}`;
                        const pOpen = openPayer === pKey;
                        const marker = tdsLimitMarker(p.payer);
                        const left = row.type === "bond" && isCurrent ? couponsLeft(p) : 0;
                        return (
                          <li key={pKey} className="min-w-0">
                            <button
                              type="button"
                              aria-expanded={pOpen}
                              onClick={() => setOpenPayer(pOpen ? null : pKey)}
                              className={`flex w-full items-start justify-between gap-3 rounded-md px-1.5 py-1.5 text-left text-[13.2px] ${ROW_FOCUS}`}
                            >
                              <span className="flex min-w-0 items-start gap-2">
                                <span className="mt-0.5">
                                  <Chevron open={pOpen} />
                                </span>
                                <span className="min-w-0">
                                  <span className="block truncate" title={p.name}>
                                    {p.name}
                                  </span>
                                  {left > 0 && (
                                    <span className="block text-xs text-muted-foreground">
                                      {couponsLeftText(left)}
                                    </span>
                                  )}
                                  {marker && (
                                    <span
                                      className={`block text-xs ${marker.over ? "text-amber-400" : "text-muted-foreground"}`}
                                    >
                                      {marker.text}
                                    </span>
                                  )}
                                </span>
                              </span>
                              <span className="shrink-0 text-right">
                                <span className="num">{formatINRWhole(p.interest_projected)}</span>
                                <span className="num text-muted-foreground">
                                  {tdsSuffix(p.tds_estimate)}
                                </span>
                              </span>
                            </button>

                            {pOpen && (
                              <ul className={`mb-1 ml-4 flex flex-col border-l border-border/50 pl-2 ${EXPAND_IN}`}>
                                {p.holdings.map((h) => {
                                  const hKey = `${h.type}-${h.id}`;
                                  const payments = h.payments ?? [];
                                  const canOpenHolding = payments.length > 0;
                                  const hOpen = canOpenHolding && openHolding === hKey;
                                  const hCls = `flex w-full items-start justify-between gap-3 rounded-md px-1.5 py-1 text-left text-xs ${ROW_FOCUS}`;
                                  const figures = (
                                    <span className="shrink-0 text-right text-muted-foreground">
                                      <span className="num">{formatINRWhole(h.interest_projected)}</span>
                                      <span className="num">{tdsSuffix(h.tds_estimate)}</span>
                                    </span>
                                  );
                                  return (
                                    <li key={hKey} className="min-w-0">
                                      {canOpenHolding ? (
                                        <div
                                          role="button"
                                          tabIndex={0}
                                          aria-expanded={hOpen}
                                          onClick={() => setOpenHolding(hOpen ? null : hKey)}
                                          onKeyDown={(e) => {
                                            if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                                              e.preventDefault();
                                              setOpenHolding(hOpen ? null : hKey);
                                            }
                                          }}
                                          className={`${hCls} cursor-pointer`}
                                        >
                                          <span className="flex min-w-0 items-start gap-2">
                                            <span className="mt-0.5">
                                              <Chevron open={hOpen} />
                                            </span>
                                            <span className="min-w-0">
                                              <Link
                                                href={`/portfolio/${h.type}/${h.id}`}
                                                onClick={(e) => e.stopPropagation()}
                                                className="block truncate hover:underline"
                                                title={h.name}
                                              >
                                                {h.name}
                                              </Link>
                                              {h.subtitle && (
                                                <span className="block truncate text-xs text-muted-foreground">
                                                  {h.subtitle}
                                                </span>
                                              )}
                                            </span>
                                          </span>
                                          {figures}
                                        </div>
                                      ) : (
                                        <Link href={`/portfolio/${h.type}/${h.id}`} className={hCls}>
                                          <span className="min-w-0">
                                            <span className="block truncate" title={h.name}>
                                              {h.name}
                                            </span>
                                            {h.subtitle && (
                                              <span className="block truncate text-xs text-muted-foreground">
                                                {h.subtitle}
                                              </span>
                                            )}
                                          </span>
                                          {figures}
                                        </Link>
                                      )}

                                      {hOpen && (
                                        <ul className={`mb-1 ml-4 flex flex-col border-l border-border/50 pl-2 ${EXPAND_IN}`}>
                                          {payments.map((pay) => (
                                            <li
                                              key={pay.date}
                                              className="flex items-start justify-between gap-3 rounded-md px-1.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted/40"
                                            >
                                              <span className="min-w-0">
                                                {formatDate(pay.date)}{" "}
                                                <span className="text-[11px]">
                                                  {pay.paid ? "Paid" : "Upcoming"}
                                                </span>
                                              </span>
                                              <span className="num shrink-0 text-right">
                                                {formatINR(pay.gross)}
                                                {tdsSuffix(pay.tds, true)}
                                              </span>
                                            </li>
                                          ))}
                                        </ul>
                                      )}
                                    </li>
                                  );
                                })}
                              </ul>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
