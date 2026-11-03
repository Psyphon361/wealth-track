import Link from "next/link";
import { Award } from "lucide-react";
import { Card } from "@/components/ui/card";
import { getAssetEntry } from "@/lib/asset-catalog";
import { rankLabel, relativeBarWidth, signedPct1, signedWhole } from "@/lib/returns";
import { ASSET_TYPE_LABELS, type RankedHolding } from "@/lib/types";

const LABEL = "text-[11px] font-medium uppercase tracking-wider text-muted-foreground";

const STYLES = {
  gain: {
    tile: "border-gain/25 bg-gradient-to-br from-gain/12 to-transparent hover:border-gain/50 hover:from-gain/20",
    top: "from-gain/20 border-gain/40",
    text: "text-gain",
    pill: "bg-gain/15 text-gain",
    icon: "bg-gain/15 text-gain",
    bar: "bg-gain",
    word: "gained",
  },
  loss: {
    tile: "border-loss/25 bg-gradient-to-br from-loss/12 to-transparent hover:border-loss/50 hover:from-loss/20",
    top: "from-loss/20 border-loss/40",
    text: "text-loss",
    pill: "bg-loss/15 text-loss",
    icon: "bg-loss/15 text-loss",
    bar: "bg-loss",
    word: "lost",
  },
} as const;

function Tile({
  h,
  index,
  reference,
  tone,
}: {
  h: RankedHolding;
  index: number;
  reference: number;
  tone: keyof typeof STYLES;
}) {
  const s = STYLES[tone];
  const Icon = getAssetEntry(h.type)?.icon;
  const emphasis = index === 0;
  return (
    <li className="min-w-0">
      <Link
        href={`/portfolio/${h.type}/${h.id}`}
        className={`group flex h-full flex-col gap-2 rounded-xl border p-3 transition duration-150 hover:-translate-y-0.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${s.tile} ${emphasis ? s.top : ""}`}
      >
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[11px] font-medium ${s.pill}`}
          >
            {emphasis && tone === "gain" && <Award className="size-3" aria-hidden="true" />}
            <span className="num">{rankLabel(index)}</span>
          </span>
          <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground">
            {Icon && (
              <span
                className={`flex size-5 shrink-0 items-center justify-center rounded-md ${s.icon}`}
              >
                <Icon className="size-3" />
              </span>
            )}
            <span className="truncate">{ASSET_TYPE_LABELS[h.type]}</span>
          </span>
        </div>
        <p className="line-clamp-2 min-h-[2.6em] text-[13.5px] font-medium leading-snug" title={h.name}>
          {h.name}
        </p>
        <div>
          <p className="flex items-baseline gap-1.5">
            <span className={`num text-xl font-semibold ${s.text}`}>{signedPct1(h.return_pct)}</span>
            <span className="text-[11px] text-muted-foreground">a year</span>
          </p>
          <p className="num text-[13.2px] text-muted-foreground">
            {signedWhole(h.gain)} {s.word}
          </p>
        </div>
        <div className="mt-auto h-1 overflow-hidden rounded-full bg-muted/50">
          <div
            className={`h-full rounded-full ${s.bar}`}
            style={{ width: `${relativeBarWidth(h.return_pct, reference)}%` }}
          />
        </div>
      </Link>
    </li>
  );
}

function Tiles({
  title,
  items,
  tone,
}: {
  title?: string;
  items: RankedHolding[];
  tone: keyof typeof STYLES;
}) {
  const reference = items[0]?.return_pct ?? 0;
  return (
    <div className="min-w-0">
      {title && <p className={`${LABEL} mb-2`}>{title}</p>}
      <ul className="grid grid-cols-1 gap-2.5 sm:grid-cols-[repeat(2,minmax(0,260px))] lg:grid-cols-[repeat(5,minmax(0,260px))]">
        {items.map((h, i) => (
          <Tile key={`${h.type}-${h.id}`} h={h} index={i} reference={reference} tone={tone} />
        ))}
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
  if (best.length === 0 && worst.length === 0) return null;
  return (
    <Card size="sm" className="min-w-0 gap-3 px-4">
      <div>
        <p className={LABEL}>Top performers</p>
        <p className="text-[13.2px] text-muted-foreground">
          Highest returns a year among holdings held over a year
        </p>
      </div>
      {best.length > 0 && <Tiles items={best} tone="gain" />}
      {worst.length > 0 && <Tiles title="Lagging" items={worst} tone="loss" />}
    </Card>
  );
}
