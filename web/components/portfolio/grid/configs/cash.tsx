import { AssetForm } from "@/components/forms/asset-form";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { CASH_KIND_LABELS, type CashItem } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  kind: "Type",
  current_value: "Balance",
  interest_rate: "Interest rate",
  balance_date: "Updated",
};

const rowName = (r: CashItem) => r.name;

const kit = createColumnKit<CashItem>("cash", labels, rowName);

export const cashConfig: GridConfig<CashItem> = {
  type: "cash",
  noun: "Cash Accounts",
  searchPlaceholder: "Search cash…",
  sortKeys: ["name", "kind", "balance_date", "current_value", "interest_rate"],
  filters: [
    { kind: "facet", key: "kind", title: "Type", labels: CASH_KIND_LABELS },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "name",
      (r) => r.name,
      () => null,
    ),
    kit.text("kind", (r) => CASH_KIND_LABELS[r.kind]),
    kit.money("current_value", (r) => r.current_value),
    kit.text(
      "interest_rate",
      (r) => (r.interest_rate == null ? null : formatPct(r.interest_rate)),
      (r) =>
        r.interest_rate == null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className="num whitespace-nowrap">
            {formatPct(r.interest_rate)}
          </span>
        ),
    ),
    kit.date("balance_date", (r) => r.balance_date),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => CASH_KIND_LABELS[r.kind],
    kpi: (r) => ({
      label: "Interest rate",
      value:
        r.interest_rate == null ? (
          "—"
        ) : (
          <span className="num">{formatPct(r.interest_rate)}</span>
        ),
      sub: "per year",
    }),
    holding: (r) => [
      { label: "Type", value: CASH_KIND_LABELS[r.kind] },
      { label: "Balance", value: formatINR(r.current_value), figure: true },
      {
        label: "Interest rate",
        value: r.interest_rate == null ? null : formatPct(r.interest_rate),
        figure: true,
      },
      {
        label: "Balance as of",
        value: formatDate(r.balance_date),
        figure: true,
      },
    ],
    instrument: () => [],
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="cash" record={row} onSaved={onSaved} />
  ),
};
