"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Loader2, TriangleAlert } from "lucide-react";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { UpdateValueDialog } from "@/components/portfolio/update-value-dialog";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiGet } from "@/lib/api";
import { getAssetEntry } from "@/lib/asset-catalog";
import {
  attentionToggleLabel,
  attentionTotal,
  dueText,
  holdingHref,
  lastUpdatedText,
  maturingAmountText,
  maturingLine,
  rateText,
  sipHref,
  visibleRows,
} from "@/lib/attention";
import { formatINR } from "@/lib/format";
import { notify } from "@/lib/notify";
import type {
  Attention,
  AttentionStale,
  AssetType,
  HoldingDetailResponse,
  HoldingRow,
} from "@/lib/types";
import { cn } from "@/lib/utils";

/** Maturities, stale balances and SIPs due soon. Hidden when there is nothing. */
export function AttentionCard({
  attention,
  onChanged,
}: {
  attention: Attention;
  onChanged: () => void;
}) {
  const total = attentionTotal(attention);
  if (total === 0) return null;

  return (
    <Card
      size="sm"
      className="min-w-0 gap-3 border border-primary/40 bg-primary/[0.04] px-4"
    >
      <div className="flex items-center gap-3">
        <span
          className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary"
          aria-hidden="true"
        >
          <TriangleAlert className="size-4" />
        </span>
        <p className="num text-[15.4px] font-medium">Needs Attention · {total}</p>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {attention.maturing.length > 0 ? (
          <MaturingGroup rows={attention.maturing} count={attention.counts.maturing} />
        ) : null}
        {attention.stale.length > 0 ? (
          <StaleGroup
            rows={attention.stale}
            count={attention.counts.stale}
            onChanged={onChanged}
          />
        ) : null}
        {attention.sips.length > 0 ? (
          <SipGroup rows={attention.sips} count={attention.counts.sips} />
        ) : null}
      </div>
    </Card>
  );
}

function Group<T>({
  title,
  count,
  rows,
  render,
}: {
  title: string;
  count: number;
  rows: T[];
  render: (row: T) => React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const toggle = attentionToggleLabel(rows.length, expanded);
  return (
    <section className="min-w-0 space-y-1.5" aria-label={title}>
      <h3 className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {title} · <span className="num">{count}</span>
      </h3>
      <ul className="flex flex-col divide-y divide-border/50 overflow-hidden rounded-lg border border-border/60 bg-card">
        {visibleRows(rows, expanded).map(render)}
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
            className={cn("size-3.5 transition-transform", expanded && "rotate-180")}
            aria-hidden="true"
          />
        </button>
      ) : null}
    </section>
  );
}

const ROW = "flex items-center gap-2.5 px-3 py-2 text-[13.5px]";
const NAME = "block truncate font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-sm";
const SUB = "num block truncate text-xs text-muted-foreground";

function TypeIcon({ type }: { type: AssetType }) {
  const entry = getAssetEntry(type);
  return entry ? <AssetTypeIcon icon={entry.icon} /> : null;
}

function MaturingGroup({
  rows,
  count,
}: {
  rows: Attention["maturing"];
  count: number;
}) {
  return (
    <Group
      title="Maturing Soon"
      count={count}
      rows={rows}
      render={(r) => {
        const rate = rateText(r.rate);
        return (
          <li key={`${r.type}-${r.id}`} className={ROW}>
            <TypeIcon type={r.type} />
            <span className="min-w-0 flex-1">
              <Link href={holdingHref(r.type, r.id)} className={NAME}>
                {r.name}
              </Link>
              <span className={SUB}>{maturingLine(r.date, r.days_left)}</span>
            </span>
            <span className="num shrink-0 text-right">
              {maturingAmountText(r.amount, r.approximate)}
              {rate ? (
                <span className="block text-xs text-muted-foreground">{rate}</span>
              ) : null}
            </span>
          </li>
        );
      }}
    />
  );
}

function StaleGroup({
  rows,
  count,
  onChanged,
}: {
  rows: AttentionStale[];
  count: number;
  onChanged: () => void;
}) {
  const [loadingKey, setLoadingKey] = useState<string | null>(null);
  const [open, setOpen] = useState<{
    item: AttentionStale;
    row: HoldingRow;
  } | null>(null);

  async function openUpdate(item: AttentionStale) {
    setLoadingKey(`${item.type}-${item.id}`);
    try {
      const res = await apiGet<HoldingDetailResponse>(
        `/holdings/${item.type}/${item.id}`,
      );
      setOpen({ item, row: res.item });
    } catch (e) {
      notify.error(e);
    } finally {
      setLoadingKey(null);
    }
  }

  return (
    <>
      <Group
        title="Stale Balances"
        count={count}
        rows={rows}
        render={(r) => {
          const key = `${r.type}-${r.id}`;
          const busy = loadingKey === key;
          return (
            <li key={key} className={ROW}>
              <TypeIcon type={r.type} />
              <span className="min-w-0 flex-1">
                <Link href={holdingHref(r.type, r.id)} className={NAME}>
                  {r.name}
                </Link>
                <span className={SUB}>{lastUpdatedText(r.as_of)}</span>
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={loadingKey !== null}
                onClick={() => openUpdate(r)}
                aria-label={`Update ${r.name}`}
              >
                {busy ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
                {busy ? "Loading…" : "Update"}
              </Button>
            </li>
          );
        }}
      />
      <UpdateValueDialog
        type={open?.item.type ?? "cash"}
        row={open?.row ?? null}
        name={open?.item.name ?? ""}
        onClose={() => setOpen(null)}
        onSaved={onChanged}
      />
    </>
  );
}

function SipGroup({ rows, count }: { rows: Attention["sips"]; count: number }) {
  return (
    <Group
      title="SIPs This Week"
      count={count}
      rows={rows}
      render={(r) => {
        const href = sipHref(r.mutual_fund_id);
        return (
          <li key={r.id} className={ROW}>
            <span className="min-w-0 flex-1">
              {href ? (
                <Link href={href} className={NAME}>
                  {r.fund_name}
                </Link>
              ) : (
                <span className="block truncate font-medium">{r.fund_name}</span>
              )}
              <span className={SUB}>{dueText(r.next_date)}</span>
            </span>
            <span className="num shrink-0 text-right">{formatINR(r.amount)}</span>
          </li>
        );
      }}
    />
  );
}
