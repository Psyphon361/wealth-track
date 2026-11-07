import { AssetForm } from "@/components/forms/asset-form";
import { cn } from "@/lib/utils";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import type { OtherItem } from "@/lib/types";
import type { GridConfig } from "../types";
import { gainTone } from "../gain-cell";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  category: "Category",
  current_value: "Value",
  invested: "Invested",
  gain: "Gain",
  value_date: "As of",
};

const rowName = (r: OtherItem) => r.name;

const kit = createColumnKit<OtherItem>("other", labels, rowName);

const dash = <span className="text-muted-foreground">—</span>;

/** Whole days from an ISO date to today (local time), never negative. */
function daysSince(iso: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return 0;
  const then = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const now = new Date();
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(Math.round((today - then) / 86_400_000), 0);
}

function agoText(iso: string): string {
  const d = daysSince(iso);
  if (d === 0) return "today";
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

export const otherConfig: GridConfig<OtherItem> = {
  type: "other",
  noun: "Other holdings",
  searchPlaceholder: "Search other holdings…",
  sortKeys: ["name", "category", "current_value", "invested", "gain", "value_date"],
  filters: [{ kind: "facet", key: "category", title: "Category" }],
  statusTabs: true,
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "name",
      (r) => r.name,
      () => null,
    ),
    kit.text("category", (r) => r.category),
    kit.money("current_value", (r) => r.current_value),
    kit.text(
      "invested",
      (r) => (r.invested_amount == null ? null : formatINR(r.invested_amount)),
      (r) =>
        r.invested_amount == null ? (
          dash
        ) : (
          <span className="num whitespace-nowrap">
            {formatINR(r.invested_amount)}
          </span>
        ),
    ),
    kit.text(
      "gain",
      (r) => (r.gain == null ? null : String(r.gain)),
      (r) =>
        r.gain == null ? (
          dash
        ) : (
          <span className={cn("num whitespace-nowrap", gainTone(r.gain))}>
            {r.gain > 0 ? "+" : ""}
            {formatINR(r.gain)}
          </span>
        ),
    ),
    kit.date("value_date", (r) => r.value_date),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => r.category,
    kpi: (r) => ({
      label: "Value as of",
      value: <span className="num">{formatDate(r.value_date)}</span>,
      sub: `Updated ${agoText(r.value_date)}`,
    }),
    holding: (r) => [
      { label: "Category", value: r.category },
      { label: "Current value", value: formatINR(r.current_value), figure: true },
      {
        label: "Value as of",
        value: `${formatDate(r.value_date)} (${agoText(r.value_date)})`,
        figure: true,
      },
      {
        label: "Amount invested",
        value: r.invested_amount == null ? null : formatINR(r.invested_amount),
        figure: true,
      },
      {
        label: "Gain",
        value:
          r.gain == null
            ? null
            : `${r.gain > 0 ? "+" : ""}${formatINR(r.gain)}${
                r.gain_pct == null ? "" : ` (${formatPct(r.gain_pct)})`
              }`,
        figure: true,
      },
      {
        label: "Purchase date",
        value: r.acquired_on ? formatDate(r.acquired_on) : null,
        figure: true,
      },
    ],
    instrument: () => [],
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="other" record={row} onSaved={onSaved} />
  ),
};
