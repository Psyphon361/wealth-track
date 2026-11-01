import { AssetForm } from "@/components/forms/asset-form";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  GOLD_FORM_LABELS,
  GOLD_METAL_LABELS,
  GOLD_PURITY_FACET_LABELS,
  goldPurityLabel,
  type GoldItem,
} from "@/lib/types";
import { gainTone } from "../gain-cell";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  metal: "Metal",
  form: "Form",
  purity: "Purity",
  weight_grams: "Weight (g)",
  purchase_date: "Purchase",
  invested: "Invested",
  current_value: "Current",
  gain: "Gain",
  xirr: "XIRR",
};

const weight = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

const rowName = (r: GoldItem) => r.name;

const kit = createColumnKit<GoldItem>("gold", labels, rowName);

export const goldConfig: GridConfig<GoldItem> = {
  type: "gold",
  noun: "Gold & Silver holdings",
  searchPlaceholder: "Search Gold & Silver…",
  sortKeys: [
    "name",
    "metal",
    "purchase_date",
    "weight_grams",
    "invested",
    "current_value",
    "gain",
    "xirr",
  ],
  filters: [
    { kind: "facet", key: "metal", title: "Metal", labels: GOLD_METAL_LABELS },
    { kind: "facet", key: "form", title: "Form", labels: GOLD_FORM_LABELS },
    { kind: "facet", key: "purity", title: "Purity", labels: GOLD_PURITY_FACET_LABELS },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "name",
      (r) => r.name,
      () => null,
    ),
    kit.text("metal", (r) => GOLD_METAL_LABELS[r.metal]),
    kit.text("form", (r) => GOLD_FORM_LABELS[r.form]),
    kit.text("purity", (r) => goldPurityLabel(r.metal, r.purity)),
    kit.number("weight_grams", (r) => r.weight_grams, (n) => weight.format(n)),
    kit.date("purchase_date", (r) => r.purchase_date),
    kit.money("invested", (r) => r.invested),
    kit.money("current_value",(r) => r.current_value),
    kit.gain(),
    kit.nullablePercent("xirr", (r) => r.xirr),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) =>
      [
        GOLD_METAL_LABELS[r.metal],
        GOLD_FORM_LABELS[r.form],
        goldPurityLabel(r.metal, r.purity),
      ].join(" · "),
    kpi: (r) => ({
      label: "Rate",
      value:
        r.rate_per_gram === null ? (
          "—"
        ) : (
          <span className="num">{formatINR(r.rate_per_gram)}/g</span>
        ),
      sub: r.rate_date ? `IBJA, ${formatDate(r.rate_date)}` : undefined,
    }),
    holding: (r) => [
      { label: "Metal", value: GOLD_METAL_LABELS[r.metal] },
      { label: "Form", value: GOLD_FORM_LABELS[r.form] },
      { label: "Purity", value: goldPurityLabel(r.metal, r.purity) },
      { label: "Weight", value: `${weight.format(r.weight_grams)} g`, figure: true },
      { label: "Purchase date", value: formatDate(r.purchase_date), figure: true },
      { label: "Total invested", value: formatINR(r.invested), figure: true },
      {
        label: "Rate",
        value:
          r.rate_per_gram === null
            ? "No rate yet – valued at cost"
            : `${formatINR(r.rate_per_gram)}/g${r.rate_date ? ` · IBJA, ${formatDate(r.rate_date)}` : ""}`,
        figure: r.rate_per_gram !== null,
      },
      {
        label: "XIRR",
        value:
          r.xirr == null ? null : (
            <span className={cn("num", gainTone(r.xirr))}>
              {r.xirr > 0 ? "+" : ""}
              {formatPct(r.xirr)}
            </span>
          ),
      },
    ],
    instrument: () => [],
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="gold" record={row} onSaved={onSaved} />
  ),
};
