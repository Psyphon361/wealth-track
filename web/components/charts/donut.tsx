"use client";

import { useEffect, useState } from "react";
import { Pie, PieChart, Sector } from "recharts";
import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import { cn } from "@/lib/utils";

const config = {} satisfies ChartConfig;

export interface DonutSlice {
  key: string;
  label: string;
  value: number;
  percent: number;
  color: string;
}

interface DonutProps {
  slices: DonutSlice[];
  total: number;
  caption: string;
  /** Controlled highlighted slice key (null = none). Omit for uncontrolled. */
  activeKey?: string | null;
  onActiveChange?: (key: string | null) => void;
  /** Called when a slice is clicked. */
  onSliceClick?: (key: string) => void;
  ariaLabel?: string;
  className?: string;
}

const GROW = 4;

function compact2(n: number): string {
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)}Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)}L`;
  return `${sign}₹${Math.round(a).toLocaleString("en-IN")}`;
}

export function Donut({
  slices,
  total,
  caption,
  activeKey,
  onActiveChange,
  onSliceClick,
  ariaLabel,
  className,
}: DonutProps) {
  const [inner, setInner] = useState<string | null>(null);
  const [animate, setAnimate] = useState(true);
  const controlled = activeKey !== undefined;
  const active = controlled ? activeKey : inner;
  const activeSlice = slices.find((s) => s.key === active) ?? null;

  useEffect(() => {
    const t = setTimeout(() => setAnimate(false), 700);
    return () => clearTimeout(t);
  }, []);

  function setActive(key: string | null) {
    if (!controlled) setInner(key);
    onActiveChange?.(key);
  }

  return (
    <div className={cn("relative mx-auto aspect-square w-full max-w-[200px]", className)}>
      <ChartContainer
        config={config}
        className="aspect-square h-full w-full"
        aria-label={ariaLabel}
        role="img"
      >
        <PieChart>
          <Pie
            data={slices}
            dataKey="value"
            nameKey="label"
            innerRadius="66%"
            outerRadius="92%"
            startAngle={90}
            endAngle={-270}
            paddingAngle={2}
            cornerRadius={4}
            stroke="none"
            isAnimationActive={animate}
            animationDuration={600}
            animationEasing="ease-out"
            onMouseEnter={(_, i) => setActive(slices[i]?.key ?? null)}
            onMouseLeave={() => setActive(null)}
            onClick={(_, i) => {
              const s = slices[i];
              if (s && onSliceClick) onSliceClick(s.key);
            }}
            shape={(props: unknown) => {
              const p = props as React.ComponentProps<typeof Sector> & {
                payload: DonutSlice;
              };
              const s = p.payload;
              const isActive = s.key === active;
              return (
                <Sector
                  {...p}
                  fill={s.color}
                  stroke="none"
                  outerRadius={(p.outerRadius ?? 0) + (isActive ? GROW : 0)}
                  style={{
                    opacity: active && !isActive ? 0.35 : 1,
                    transition: "opacity 150ms ease",
                    cursor: onSliceClick ? "pointer" : undefined,
                    outline: "none",
                  }}
                />
              );
            }}
          />
        </PieChart>
      </ChartContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-[22%] text-center">
        {activeSlice ? (
          <>
            <span className="max-w-full truncate text-[11px] uppercase tracking-wider text-muted-foreground">
              {activeSlice.label}
            </span>
            <span className="num text-base font-semibold leading-tight">
              {compact2(activeSlice.value)}
            </span>
            <span className="num text-[13.2px] text-muted-foreground">
              {activeSlice.percent.toFixed(1)}%
            </span>
          </>
        ) : (
          <>
            <span className="num text-base font-semibold leading-tight">
              {compact2(total)}
            </span>
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
              {caption}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
