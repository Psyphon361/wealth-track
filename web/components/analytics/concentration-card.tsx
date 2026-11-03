"use client";

import { useState } from "react";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MORE_COLOR } from "@/lib/asset-colors";
import { formatINR, formatPct } from "@/lib/format";
import { ASSET_TYPE_LABELS, type AnalyticsConcentration } from "@/lib/types";

const TOP = "top10";
const OTHERS = "others";

const LABELS: Record<string, string> = {
  stock: "Stocks",
  mf_amc: "Mutual Fund AMCs",
  bank: "Banks",
  bond_issuer: "Bond Issuers",
  nps_pfm: "NPS Managers",
};

const NOUNS: Record<string, string> = {
  [TOP]: "holding",
  stock: "stock",
  mf_amc: "AMC",
  bank: "bank",
  bond_issuer: "bond issuer",
  nps_pfm: "NPS manager",
};

interface Row {
  key: string;
  name: string;
  hint: string | null;
  value: number;
  percent: number;
  href: string | null;
}

/** One hue, fading by rank (same approach as the Liquidity card). */
function shade(rank: number, count: number): string {
  const t = count <= 1 ? 0 : rank / (count - 1);
  const l = 0.8 - t * 0.42;
  const c = 0.16 - t * 0.09;
  return `oklch(${l.toFixed(3)} ${c.toFixed(3)} 265)`;
}

export function ConcentrationCard({ concentration }: { concentration: AnalyticsConcentration }) {
  const [view, setView] = useState<string>(TOP);
  const [active, setActive] = useState<string | null>(null);
  const rollups = concentration.rollups.filter((r) => r.bars.length > 0);
  const rollup = rollups.find((r) => r.key === view);
  const current = rollup ? view : TOP;
  const items = [{ key: TOP, label: "Top 10" }, ...rollups.map((r) => ({ key: r.key, label: LABELS[r.key] ?? r.label }))];

  const rows: Row[] = rollup
    ? rollup.bars.map((b) => ({
        key: b.key,
        name: b.label,
        hint: b.passive ? "ETF" : null,
        value: b.value,
        percent: b.percent,
        href: null,
      }))
    : concentration.top_holdings.map((h) => ({
        key: `${h.type}-${h.id}`,
        name: h.name,
        hint: ASSET_TYPE_LABELS[h.type] ?? null,
        value: h.value,
        percent: h.percent,
        href: `/portfolio/${h.type}/${h.id}`,
      }));

  const shadedCount = rows.length;
  if (!rollup && concentration.others && concentration.others.count > 0) {
    const n = concentration.others.count;
    rows.push({
      key: OTHERS,
      name: "Everything else",
      hint: `${n} more ${n === 1 ? "holding" : "holdings"}`,
      value: concentration.others.value,
      percent: concentration.others.percent,
      href: null,
    });
  }
  const colorFor = (r: Row, i: number) => (r.key === OTHERS ? MORE_COLOR : shade(i, shadedCount));

  const largest = rows
    .filter((r) => r.key !== OTHERS)
    .reduce<Row | null>((m, r) => (m === null || r.percent > m.percent ? r : m), null);
  const maxPct = Math.max(...rows.map((r) => r.percent), 0.0001);
  const dim = (key: string) => (active !== null && active !== key ? "opacity-40" : "opacity-100");

  return (
    <Card size="sm" className="h-full min-w-0 gap-3 px-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Concentration
          </p>
          <CardInfo>
            Your largest holdings, and how much sits with one company, fund house, bank, bond
            issuer or pension fund manager. It flags a single stock above 10% of your equity or
            a fund house above 30% of your mutual funds.
          </CardInfo>
        </div>
        <Select
          items={items.map((i) => ({ value: i.key, label: i.label }))}
          value={current}
          onValueChange={(v) => {
            setView(v ?? TOP);
            setActive(null);
          }}
        >
          <SelectTrigger size="sm" className="text-xs" aria-label="Concentration view">
            <SelectValue />
          </SelectTrigger>
          <SelectContent alignItemWithTrigger={false}>
            {items.map((i) => (
              <SelectItem key={i.key} value={i.key}>
                {i.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {concentration.flags.length > 0 && (
        <ul className="space-y-0.5">
          {concentration.flags.map((f) => (
            <li
              key={`${f.kind}-${f.key}`}
              className="flex items-start gap-1.5 text-[13.2px] text-amber-400"
            >
              <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden="true" />
              <span>
                {f.label} is <span className="num">{formatPct(f.percent)}</span> of{" "}
                {f.kind === "amc" ? "mutual funds" : "equity"}, over{" "}
                <span className="num">
                  {Number.isInteger(f.threshold) ? `${f.threshold}%` : formatPct(f.threshold)}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {largest === null ? (
        <p className="py-4 text-center text-xs text-muted-foreground">Nothing to show</p>
      ) : (
        <>
          <div>
            <p className="num text-xl font-semibold">{formatPct(largest.percent)}</p>
            <p className="min-w-0 truncate text-[13.2px] text-muted-foreground" title={largest.name}>
              {largest.name} is your largest {NOUNS[current] ?? "item"}
            </p>
          </div>
          <div className="mt-2 flex h-2.5 gap-0.5" onMouseLeave={() => setActive(null)}>
            {rows.map((r, i) => (
              <div
                key={r.key}
                onMouseEnter={() => setActive(r.key)}
                title={r.name}
                className={`h-full rounded-full transition-opacity duration-150 ${dim(r.key)}`}
                style={{
                  width: `${Math.min(100, Math.max(0, r.percent))}%`,
                  minWidth: 2,
                  backgroundColor: colorFor(r, i),
                }}
                aria-hidden="true"
              />
            ))}
          </div>
          <ul
            className="mt-3 grid grid-cols-1 gap-x-6 md:grid-cols-2"
            onMouseLeave={() => setActive(null)}
          >
            {rows.map((r, i) => {
              const color = colorFor(r, i);
              const body = (
                <>
                  <span
                    className="size-2 shrink-0 rounded-full"
                    style={{ backgroundColor: color }}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate" title={r.name}>
                      {r.name}
                    </span>
                    {r.hint && (
                      <span className="block truncate text-xs text-muted-foreground">{r.hint}</span>
                    )}
                    <span className="mt-1 block h-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                      <span
                        className="block h-full rounded-full"
                        style={{
                          width: `${Math.min(100, Math.max(0, (r.percent / maxPct) * 100))}%`,
                          backgroundColor: color,
                        }}
                      />
                    </span>
                  </span>
                  <span className="num shrink-0 text-right">{formatINR(r.value)}</span>
                  <span className="num w-14 shrink-0 text-right text-muted-foreground">
                    {formatPct(r.percent)}
                  </span>
                </>
              );
              const cls = `flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${dim(r.key)}`;
              return (
                <li key={r.key} onMouseEnter={() => setActive(r.key)} className="min-w-0">
                  {r.href ? (
                    <Link href={r.href} className={cls}>
                      {body}
                    </Link>
                  ) : (
                    <div className={cls}>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Card>
  );
}
