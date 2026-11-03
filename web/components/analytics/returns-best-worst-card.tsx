import Link from "next/link";
import { Card } from "@/components/ui/card";
import { signedPct1 } from "@/lib/returns";
import type { RankedHolding } from "@/lib/types";

function tone(n: number): string {
  return n > 0 ? "text-gain" : n < 0 ? "text-loss" : "";
}

function List({ title, items }: { title: string; items: RankedHolding[] }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        {title}
      </p>
      <ul className="mt-2 flex flex-col">
        {items.map((h) => (
          <li
            key={`${h.type}-${h.id}`}
            className="flex items-center gap-3 rounded-md px-1.5 py-1.5 text-[13.5px] hover:bg-muted/40"
          >
            <Link
              href={`/portfolio/${h.type}/${h.id}`}
              className="min-w-0 flex-1 truncate hover:underline"
            >
              {h.name}
            </Link>
            <span className={`num shrink-0 text-right ${tone(h.return_pct)}`}>
              {signedPct1(h.return_pct)}
            </span>
          </li>
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
      <div className="grid gap-4 lg:grid-cols-2">
        {best.length > 0 && <List title="Best" items={best} />}
        {worst.length > 0 && <List title="Worst" items={worst} />}
      </div>
    </Card>
  );
}
