import { AssetForm } from "@/components/forms/asset-form";
import {
  NPS_ASSET_CLASS_LABELS,
  NPS_TIER_LABELS,
  type NpsItem,
  type NpsScheme,
} from "@/lib/types";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { gainTone } from "../gain-cell";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  scheme_name: "Scheme",
  tier: "Tier",
  asset_class: "Class",
  units: "Units",
  nav: "NAV",
  contributed: "Contributed",
  current_value: "Current value",
  gain: "Gain",
  gain_pct: "Gain %",
  start_date: "Started on",
};

const rowName = (r: NpsItem) => r.scheme_name;

const kit = createColumnKit<NpsItem>("nps", labels, rowName);

const units = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});
const nav = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

const tierLabel = (t: NpsItem["tier"]) => (t ? NPS_TIER_LABELS[t] : "—");

export const npsConfig: GridConfig<NpsItem> = {
  type: "nps",
  noun: "NPS holdings",
  searchPlaceholder: "Search NPS schemes…",
  sortKeys: [
    "scheme_name",
    "pfm_name",
    "tier",
    "asset_class",
    "units",
    "nav",
    "contributed",
    "current_value",
    "gain",
    "gain_pct",
    "start_date",
  ],
  filters: [
    { kind: "facet", key: "pfm_name", title: "PFM" },
    { kind: "facet", key: "tier", title: "Tier", labels: NPS_TIER_LABELS },
    {
      kind: "facet",
      key: "asset_class",
      title: "Class",
      labels: NPS_ASSET_CLASS_LABELS,
    },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "scheme_name",
      (r) => r.scheme_name,
      (r) => r.pfm_name,
    ),
    kit.text("tier", (r) => (r.tier ? NPS_TIER_LABELS[r.tier] : null)),
    kit.text("asset_class", (r) => NPS_ASSET_CLASS_LABELS[r.asset_class]),
    kit.number("units", (r) => r.units, (n) => units.format(n)),
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
    kit.money("contributed", (r) => r.contributed),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.date("start_date", (r) => r.start_date),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => [r.pfm_name, tierLabel(r.tier)].join(" · "),
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
      { label: "Units", value: units.format(r.units), figure: true },
      {
        label: "Current NAV",
        value:
          r.nav == null
            ? "—"
            : `${nav.format(r.nav)}${r.nav_date ? ` as of ${formatDate(r.nav_date)}` : ""}`,
        figure: true,
      },
      { label: "Contributed", value: formatINR(r.contributed), figure: true },
      { label: "Current value", value: formatINR(r.current_value), figure: true },
      {
        label: "Gain",
        value: (
          <span className={cn("num", gainTone(r.gain))}>
            {r.gain > 0 ? "+" : ""}
            {formatINR(r.gain)} ({r.gain > 0 ? "+" : ""}
            {formatPct(r.gain_pct)})
          </span>
        ),
      },
      { label: "Started on", value: formatDate(r.start_date), figure: true },
    ],
    instrument: (m) => {
      const s = m as NpsScheme;
      return [
        { label: "Scheme", value: s.scheme_name },
        { label: "PFM", value: s.pfm_name },
        { label: "Tier", value: tierLabel(s.tier) },
        { label: "Class", value: NPS_ASSET_CLASS_LABELS[s.asset_class] },
      ];
    },
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="nps" record={row} onSaved={onSaved} />
  ),
};
