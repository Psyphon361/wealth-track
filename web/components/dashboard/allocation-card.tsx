"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Donut } from "@/components/charts/donut";
import { Card } from "@/components/ui/card";
import { allocationSlices, type AllocationSlice } from "@/lib/allocation";
import { assetColor, MORE_COLOR } from "@/lib/asset-colors";
import type { DashboardResponse } from "@/lib/types";

function sliceColor(s: AllocationSlice): string {
  return s.key === "more" ? MORE_COLOR : assetColor(s.key);
}

function sliceLabel(s: AllocationSlice): string {
  return s.folded ? `${s.label} (${s.folded})` : s.label;
}

function pctText(n: number): string {
  return `${n.toFixed(1)}%`;
}

export function AllocationCard({ data }: { data: DashboardResponse }) {
  const router = useRouter();
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const slices = allocationSlices(data.by_type);
  const summary = `Allocation by asset type: ${slices
    .map((s) => `${sliceLabel(s)} ${pctText(s.pct)}`)
    .join(", ")}`;

  return (
    <Card className="h-full min-w-0 gap-3 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Allocation
      </p>
      <Donut
        slices={slices.map((s) => ({
          key: s.key,
          label: sliceLabel(s),
          value: s.value,
          percent: s.pct,
          color: sliceColor(s),
        }))}
        total={data.total_current}
        caption="Net worth"
        activeKey={activeKey}
        onActiveChange={setActiveKey}
        onSliceClick={(key) => {
          if (key !== "more") router.push(`/portfolio/${key}`);
        }}
        ariaLabel={summary}
        className="max-w-[212px]"
      />
      <ul className="space-y-0.5">
        {slices.map((s) => {
          const row = (
            <>
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: sliceColor(s) }}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1 truncate text-foreground">{sliceLabel(s)}</span>
              <span className="num shrink-0 text-right text-muted-foreground">
                {pctText(s.pct)}
              </span>
            </>
          );
          const cls = `flex items-center gap-2 rounded-md px-1.5 py-1 text-[13.5px] transition-colors ${
            activeKey === s.key ? "bg-muted/40" : ""
          }`;
          return (
            <li
              key={s.key}
              onMouseEnter={() => setActiveKey(s.key)}
              onMouseLeave={() => setActiveKey(null)}
              onFocus={() => setActiveKey(s.key)}
              onBlur={() => setActiveKey(null)}
            >
              {s.key === "more" ? (
                <div className={cls}>{row}</div>
              ) : (
                <Link
                  href={`/portfolio/${s.key}`}
                  className={`${cls} hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
                >
                  {row}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
