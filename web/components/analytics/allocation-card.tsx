"use client";

import { useState } from "react";
import Link from "next/link";
import { Switch } from "@base-ui/react/switch";
import { ChevronRight } from "lucide-react";
import { Donut } from "@/components/charts/donut";
import { Card } from "@/components/ui/card";
import { CardInfo } from "@/components/analytics/card-info";
import { classColor, pctText } from "@/lib/analytics";
import { formatINR } from "@/lib/format";
import type { AnalyticsAllocation, AnalyticsAllocationClass } from "@/lib/types";

const rowCls = "flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13.5px]";
const focusCls = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function ClassRow({
  cls,
  activeKey,
  onActiveChange,
}: {
  cls: AnalyticsAllocationClass;
  activeKey: string | null;
  onActiveChange: (key: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [openTypes, setOpenTypes] = useState<Set<string>>(new Set());

  function toggleType(t: string) {
    setOpenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        onMouseEnter={() => onActiveChange(cls.class)}
        onMouseLeave={() => onActiveChange(null)}
        onFocus={() => onActiveChange(cls.class)}
        onBlur={() => onActiveChange(null)}
        className={`${rowCls} transition-colors hover:bg-muted/40 ${
          activeKey === cls.class ? "bg-muted/40" : ""
        } ${focusCls}`}
      >
        <ChevronRight
          className={`size-3.5 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden="true"
        />
        <span
          className="size-2 shrink-0 rounded-full"
          style={{ backgroundColor: classColor(cls.class) }}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate">{cls.label}</span>
        <span className="num shrink-0 text-right">{formatINR(cls.value)}</span>
        <span className="num w-12 shrink-0 text-right text-muted-foreground">
          {pctText(cls.percent)}
        </span>
      </button>
      {open && (
        <ul className="ml-5 space-y-0.5 border-l pl-2">
          {cls.types.map((t) => {
            const tOpen = openTypes.has(t.type);
            return (
              <li key={t.type}>
                <button
                  type="button"
                  onClick={() => toggleType(t.type)}
                  aria-expanded={tOpen}
                  className={`${rowCls} text-xs hover:bg-muted/50 ${focusCls}`}
                >
                  <ChevronRight
                    className={`size-3 shrink-0 text-muted-foreground transition-transform ${tOpen ? "rotate-90" : ""}`}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{t.label}</span>
                  <span className="num shrink-0 text-right">{formatINR(t.value)}</span>
                  <span className="num w-12 shrink-0 text-right text-muted-foreground">
                    {pctText(t.percent)}
                  </span>
                </button>
                {tOpen && (
                  <ul className="ml-4 space-y-0.5 border-l pl-2">
                    {t.holdings.map((h) => (
                      <li key={h.id}>
                        <Link
                          href={`/portfolio/${t.type}/${h.id}`}
                          className={`${rowCls} text-xs hover:bg-muted/50 ${focusCls}`}
                        >
                          <span className="min-w-0 flex-1 truncate">{h.name}</span>
                          <span className="num shrink-0 text-right">{formatINR(h.value)}</span>
                          <span className="num w-12 shrink-0 text-right text-muted-foreground">
                            {pctText(h.percent)}
                          </span>
                        </Link>
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
}

export function AllocationCard({ allocation }: { allocation: AnalyticsAllocation }) {
  const [includeRetirement, setIncludeRetirement] = useState(true);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const view = includeRetirement ? allocation.including_retirement : allocation.excluding_retirement;
  const summary = `Allocation by class: ${view.classes
    .map((c) => `${c.label} ${pctText(c.percent)}`)
    .join(", ")}`;

  return (
    <Card size="sm" className="h-full min-w-0 gap-3 px-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Allocation
          </p>
          <CardInfo>
            How your money is split across equity, debt, gold and silver, and cash. You can
            include or leave out retirement accounts (EPF, PPF and NPS Tier I).
          </CardInfo>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-muted-foreground">
          Include retirement
          <Switch.Root
            checked={includeRetirement}
            onCheckedChange={setIncludeRetirement}
            className="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-input p-0.5 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring data-checked:bg-primary"
          >
            <Switch.Thumb className="block size-4 rounded-full bg-foreground transition-transform data-checked:translate-x-4" />
          </Switch.Root>
        </label>
      </div>
      {view.classes.length === 0 ? (
        <p className="py-8 text-center text-xs text-muted-foreground">Nothing to show</p>
      ) : (
        <Donut
          slices={view.classes.map((c) => ({
            key: c.class,
            label: c.label,
            value: c.value,
            percent: c.percent,
            color: classColor(c.class),
          }))}
          total={view.total}
          caption="Total"
          activeKey={activeKey}
          onActiveChange={setActiveKey}
          ariaLabel={summary}
        />
      )}
      <ul className="space-y-0.5">
        {view.classes.map((c) => (
          <ClassRow key={c.class} cls={c} activeKey={activeKey} onActiveChange={setActiveKey} />
        ))}
      </ul>
      {!includeRetirement && (
        <p className="text-xs text-muted-foreground">
          Excludes <span className="num">{formatINR(allocation.retirement_value)}</span> in
          retirement (<span className="num">{pctText(allocation.retirement_percent)}</span> of
          total)
        </p>
      )}
    </Card>
  );
}
