import { AssetForm } from "@/components/forms/asset-form";
import {
  MF_CATEGORY_LABELS,
  type MfScheme,
  type MutualFundItem,
} from "@/lib/types";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { gainTone } from "../gain-cell";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  scheme_name: "Scheme",
  category: "Category",
  platform: "Platform",
  units: "Units",
  avg_nav: "Avg NAV",
  nav: "NAV",
  invested: "Invested",
  current_value: "Current",
  gain: "Gain",
  gain_pct: "Gain %",
  purchase_date: "Purchase date",
};

const rowName = (r: MutualFundItem) => r.scheme_name;

const kit = createColumnKit<MutualFundItem>("mf", labels, rowName);

export const units = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
export const nav = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export const mfConfig: GridConfig<MutualFundItem> = {
  type: "mf",
  noun: "mutual funds",
  searchPlaceholder: "Search mutual funds…",
  sortKeys: [
    "scheme_name",
    "category",
    "platform",
    "units",
    "avg_nav",
    "invested",
    "current_value",
    "gain",
    "gain_pct",
    "purchase_date",
  ],
  filters: [
    {
      kind: "facet",
      key: "category",
      title: "Category",
      labels: MF_CATEGORY_LABELS,
    },
    { kind: "facet", key: "platform", title: "Platform" },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "scheme_name",
      (r) => r.scheme_name,
      () => null,
    ),
    kit.text("category", (r) => MF_CATEGORY_LABELS[r.category]),
    kit.text("platform", (r) => r.platform),
    kit.number("units", (r) => r.units, (n) => units.format(n)),
    kit.number("avg_nav", (r) => r.avg_nav, (n) => nav.format(n)),
    kit.display("nav", (r) =>
      r.nav == null ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        <div className="leading-tight">
          <div className="num whitespace-nowrap">{nav.format(r.nav)}</div>
          {r.nav_date ? (
            <div className="text-[11px] whitespace-nowrap text-muted-foreground">
              as of {formatDate(r.nav_date)}
            </div>
          ) : null}
        </div>
      ),
    ),
    kit.money("invested", (r) => r.invested),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.date("purchase_date", (r) => r.purchase_date),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) =>
      [MF_CATEGORY_LABELS[r.category], r.platform].filter(Boolean).join(" · "),
    kpi: (r) => {
      if (r.day_change == null || r.day_change_pct == null) {
        return { label: "1-day change", value: "—" };
      }
      const tone = gainTone(r.day_change);
      const sign = r.day_change > 0 ? "+" : "";
      return {
        label: "1-day change",
        value: (
          <span className={cn("num", tone)}>
            {sign}
            {formatINR(r.day_change)}
          </span>
        ),
        sub: (
          <span className={cn("num", tone)}>
            {sign}
            {formatPct(r.day_change_pct)}
          </span>
        ),
      };
    },
    holding: (r) => [
      { label: "Scheme", value: r.scheme_name },
      { label: "Category", value: MF_CATEGORY_LABELS[r.category] },
      { label: "Platform", value: r.platform },
      { label: "Units", value: units.format(r.units), figure: true },
      { label: "Avg NAV", value: nav.format(r.avg_nav), figure: true },
      {
        label: "Current NAV",
        value:
          r.nav == null
            ? "—"
            : `${nav.format(r.nav)}${r.nav_date ? ` as of ${formatDate(r.nav_date)}` : ""}`,
        figure: true,
      },
      { label: "Purchase date", value: formatDate(r.purchase_date), figure: true },
    ],
    instrument: (m) => {
      const s = m as MfScheme;
      return [
        { label: "Scheme code", value: String(s.scheme_code), figure: true },
        { label: "AMC", value: s.amc },
        { label: "Category", value: MF_CATEGORY_LABELS[s.category] },
      ];
    },
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="mf" record={row} onSaved={onSaved} />
  ),
};
