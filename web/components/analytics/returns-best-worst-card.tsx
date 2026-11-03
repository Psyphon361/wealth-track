"use client";

import { useState } from "react";
import Link from "next/link";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { signedPct1, signedWhole } from "@/lib/returns";
import { ASSET_TYPE_LABELS, type RankedHolding } from "@/lib/types";

const LABEL = "text-[11px] font-medium uppercase tracking-wider text-muted-foreground";

const TONES = {
  gain: { text: "text-gain" },
  loss: { text: "text-loss" },
} as const;

function Rows({
  title,
  items,
  tone,
  active,
  setActive,
}: {
  title?: string;
  items: RankedHolding[];
  tone: keyof typeof TONES;
  active: string | null;
  setActive: (key: string | null) => void;
}) {
  const t = TONES[tone];
  const dim = (key: string) => (active !== null && active !== key ? "opacity-40" : "opacity-100");
  return (
    <div className="min-w-0">
      {title && <p className={`${LABEL} mb-1`}>{title}</p>}
      <ul
        className="grid grid-cols-1"
        onMouseLeave={() => setActive(null)}
      >
        {items.map((h, i) => {
          const key = `${h.type}-${h.id}`;
          return (
            <li key={key} onMouseEnter={() => setActive(key)} className="min-w-0">
              <Link
                href={`/portfolio/${h.type}/${h.id}`}
                className={`flex items-center gap-2 rounded-md px-1.5 py-1.5 text-[13.5px] transition-[opacity,background-color] duration-150 hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${dim(key)}`}
              >
                <span className="num w-2 shrink-0 text-center text-xs text-muted-foreground">
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate" title={h.name}>
                    {h.name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {ASSET_TYPE_LABELS[h.type]}
                  </span>
                </span>
                <span className="shrink-0 text-right">
                  <span className={`num block ${t.text}`}>{signedPct1(h.return_pct)}</span>
                  <span className="num block text-xs text-muted-foreground">
                    {signedWhole(h.gain)}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ReturnsBestWorstCard({
  best,
  worst,
}: {
  best: RankedHolding[];
  worst: RankedHolding[];
}) {
  const [active, setActive] = useState<string | null>(null);
  if (best.length === 0 && worst.length === 0) return null;
  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <div>
        <div className="flex items-center gap-1.5">
          <p className={LABEL}>Top performers</p>
          <CardInfo>
            Your holdings with the highest yearly returns, among those held for at least 6 months.
          </CardInfo>
        </div>
        <p className="text-[13.2px] text-muted-foreground">
          Highest yearly returns among holdings held for at least 6 months
        </p>
      </div>
      {best.length > 0 && <Rows items={best} tone="gain" active={active} setActive={setActive} />}
      {worst.length > 0 && (
        <Rows title="Lagging" items={worst} tone="loss" active={active} setActive={setActive} />
      )}
    </Card>
  );
}
