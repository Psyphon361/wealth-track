import { AssetForm } from "@/components/forms/asset-form";
import { formatPct } from "@/lib/format";
import {
  COMPOUNDING_LABELS,
  PAYOUT_TYPE_LABELS,
  type FixedDepositItem,
} from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit, STATUS_LABELS } from "./shared";

const labels = {
  bank: "Bank",
  principal: "Principal",
  rate: "Rate",
  compounding: "Compounding",
  start_date: "Start",
  maturity_date: "Maturity",
  current_value: "Current",
  gain: "Gain",
  gain_pct: "Gain %",
  status: "Status",
};

const rowName = (r: FixedDepositItem) =>
  r.label ? `${r.bank} · ${r.label}` : r.bank;

const kit = createColumnKit<FixedDepositItem>("fd", labels, rowName);

export const fdConfig: GridConfig<FixedDepositItem> = {
  type: "fd",
  noun: "fixed deposits",
  searchPlaceholder: "Search fixed deposits…",
  sortKeys: [
    "bank",
    "principal",
    "rate",
    "compounding",
    "start_date",
    "maturity_date",
    "current_value",
    "gain",
    "gain_pct",
    "status",
  ],
  filters: [
    { kind: "facet", key: "bank", title: "Bank" },
    {
      kind: "facet",
      key: "payout_type",
      title: "Payout",
      labels: PAYOUT_TYPE_LABELS,
    },
    {
      kind: "facet",
      key: "compounding",
      title: "Compounding",
      labels: COMPOUNDING_LABELS,
    },
    { kind: "facet", key: "status", title: "Status", labels: STATUS_LABELS },
    { kind: "range", title: "Rate", minKey: "rate_min", maxKey: "rate_max" },
    {
      kind: "date",
      title: "Maturity",
      fromKey: "maturity_from",
      toKey: "maturity_to",
    },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "bank",
      (r) => r.bank,
      (r) => r.label,
    ),
    kit.money("principal", (r) => r.principal),
    kit.number("rate", (r) => r.rate, formatPct),
    kit.text(
      "compounding",
      (r) => COMPOUNDING_LABELS[r.compounding],
      (r) => (
        <span className="whitespace-nowrap">
          {r.payout_type === "payout"
            ? `${PAYOUT_TYPE_LABELS.payout} · ${COMPOUNDING_LABELS[r.compounding]}`
            : COMPOUNDING_LABELS[r.compounding]}
        </span>
      ),
    ),
    kit.date("start_date", (r) => r.start_date),
    kit.date("maturity_date", (r) => r.maturity_date),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.status(),
    kit.actions(handlers),
  ],
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="fd" record={row} onSaved={onSaved} />
  ),
};
