import { AssetForm } from "@/components/forms/asset-form";
import { MF_CATEGORY_LABELS, type MutualFundItem } from "@/lib/types";
import { formatDate } from "@/lib/format";
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

const units = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
const nav = new Intl.NumberFormat("en-IN", {
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
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="mf" record={row} onSaved={onSaved} />
  ),
};
