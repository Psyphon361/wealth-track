"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Cell, Pie, PieChart } from "recharts";
import { Card } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart";
import { allocationSlices, type AllocationSlice } from "@/lib/allocation";
import { assetColor, MORE_COLOR } from "@/lib/asset-colors";
import { formatINR } from "@/lib/format";
import type { DashboardResponse } from "@/lib/types";

const config = {} satisfies ChartConfig;

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
  const slices = allocationSlices(data.by_type);
  const summary = `Allocation by asset type: ${slices
    .map((s) => `${sliceLabel(s)} ${pctText(s.pct)}`)
    .join(", ")}`;

  return (
    <Card className="h-full min-w-0 gap-3 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Allocation
      </p>
      <ChartContainer
        config={config}
        className="mx-auto aspect-square h-44 w-44 shrink-0"
        aria-label={summary}
        role="img"
      >
        <PieChart>
          <ChartTooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const s = payload[0].payload as AllocationSlice;
              return (
                <div className="grid gap-1 rounded-lg border bg-popover px-2.5 py-1.5 text-xs shadow-md">
                  <p className="font-medium">{sliceLabel(s)}</p>
                  <div className="flex justify-between gap-4">
                    <span className="num">{formatINR(s.value)}</span>
                    <span className="num text-muted-foreground">{pctText(s.pct)}</span>
                  </div>
                </div>
              );
            }}
          />
          <Pie
            data={slices}
            dataKey="value"
            nameKey="label"
            innerRadius="70%"
            outerRadius="100%"
            startAngle={90}
            endAngle={-270}
            stroke="var(--card)"
            strokeWidth={2}
            isAnimationActive={false}
          >
            {slices.map((s) => (
              <Cell
                key={s.key}
                fill={sliceColor(s)}
                stroke="var(--card)"
                strokeWidth={2}
                className={s.key === "more" ? undefined : "cursor-pointer outline-none"}
                onClick={
                  s.key === "more" ? undefined : () => router.push(`/portfolio/${s.key}`)
                }
              />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
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
          const cls = "flex items-center gap-2 rounded-md px-1.5 py-1 text-[13.5px]";
          return (
            <li key={s.key}>
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
