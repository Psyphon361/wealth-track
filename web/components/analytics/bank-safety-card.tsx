"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, ChevronRight, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDate, formatINR, formatINRCompact } from "@/lib/format";
import type { AnalyticsBankRow, AnalyticsBankSafety } from "@/lib/types";

const BADGE_LABELS: Record<string, string> = {
  not_dicgc: "Not DICGC-insured",
  cooperative: "Co-operative",
  small_finance: "Small finance",
  post_office: "Post Office (sovereign)",
};

const focusCls = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Badge({ children, warn }: { children: React.ReactNode; warn?: boolean }) {
  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-px text-[11px] ${
        warn ? "bg-amber-500/15 text-amber-400" : "bg-muted text-muted-foreground"
      }`}
    >
      {children}
    </span>
  );
}

function BankRowItem({ bank, limit }: { bank: AnalyticsBankRow; limit: number }) {
  const [open, setOpen] = useState(false);
  const over = bank.excess !== null && bank.excess > 0;
  const muted = bank.status === "unknown" || bank.status === "sovereign";
  const barCls = over ? "bg-loss" : muted ? "bg-foreground/30" : "bg-gain";
  const pct = limit > 0 ? Math.min(100, Math.max(0, (bank.total / limit) * 100)) : 0;
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`w-full space-y-1 rounded-md px-1.5 py-1 text-left text-[13.5px] hover:bg-muted/50 ${focusCls}`}
      >
        <span className="flex items-baseline gap-2">
          <span className="flex min-w-0 flex-1 items-center gap-1.5">
            <ChevronRight
              className={`size-3.5 shrink-0 self-center text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
              aria-hidden="true"
            />
            <span className="min-w-0 truncate">{bank.name}</span>
            {bank.badges
              .filter((b) => b !== "small_finance")
              .map((b) => (
                <Badge key={b} warn={b === "not_dicgc"}>
                  {BADGE_LABELS[b] ?? b}
                </Badge>
              ))}
            {bank.status === "unknown" && <Badge>Unknown</Badge>}
          </span>
          {over && (
            <span className="shrink-0 text-xs text-loss">
              <span className="num">{formatINR(bank.excess ?? 0)}</span> over
            </span>
          )}
          <span className="num shrink-0 text-right">{formatINR(bank.total)}</span>
        </span>
        <span className="block h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <span className={`block h-full rounded-full ${barCls}`} style={{ width: `${pct}%` }} />
        </span>
      </button>
      {open && (
        <ul className="ml-5 space-y-0.5 border-l pl-2">
          {bank.holdings.map((h) => (
            <li key={`${h.type}-${h.id}`}>
              <Link
                href={`/portfolio/${h.type}/${h.id}`}
                className={`flex items-center gap-2 rounded-md px-1.5 py-1 text-xs hover:bg-muted/50 ${focusCls}`}
              >
                <span className="min-w-0 flex-1 truncate">
                  {h.label ? `${h.label} · ` : ""}
                  {h.type === "rd" ? "RD" : "FD"}
                  {h.rate !== null && (
                    <>
                      {" · "}
                      <span className="num">{h.rate}%</span>
                    </>
                  )}
                  {h.maturity_date && ` · matures ${formatDate(h.maturity_date)}`}
                </span>
                <span className="num shrink-0 text-right">{formatINR(h.amount)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function BankSafetyCard({ bankSafety }: { bankSafety: AnalyticsBankSafety }) {
  const { banks, limit } = bankSafety;
  const limitLabel = formatINRCompact(limit);
  return (
    <Card size="sm" className="h-full min-w-0 gap-3 px-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Bank safety
          </p>
          <Tooltip>
            <TooltipTrigger
              aria-label="About bank safety"
              className={`rounded-full text-muted-foreground hover:text-foreground ${focusCls}`}
            >
              <Info className="size-3.5" aria-hidden="true" />
            </TooltipTrigger>
            <TooltipContent>
              FD and RD only; cash isn&apos;t linked to a bank yet. Joint accounts and different
              capacities are insured separately, so this can over-warn.
            </TooltipContent>
          </Tooltip>
        </div>
        {bankSafety.uninsured_excess > 0 ? (
          <span className="text-xs text-loss">
            <span className="num">{formatINR(bankSafety.uninsured_excess)}</span> over the{" "}
            {limitLabel} cover
          </span>
        ) : bankSafety.unknown_amount > 0 ? (
          <span className="text-xs text-muted-foreground">
            <span className="num">{formatINR(bankSafety.unknown_amount)}</span> with unknown cover
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs text-gain">
            <Check className="size-3.5" aria-hidden="true" />
            All within {limitLabel} cover
          </span>
        )}
      </div>
      {banks.length === 0 ? (
        <p className="py-4 text-center text-xs text-muted-foreground">No FDs or RDs yet</p>
      ) : (
        <ul className="space-y-1.5">
          {banks.map((b) => (
            <BankRowItem key={b.key} bank={b} limit={limit} />
          ))}
        </ul>
      )}
    </Card>
  );
}
