import { AssetForm } from "@/components/forms/asset-form";
import { formatPct } from "@/lib/format";
import type { RecurringDepositItem } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit, STATUS_LABELS } from "./shared";

const labels = {
  bank: "Bank",
  monthly_instalment: "Monthly instalment",
  rate: "Rate",
  start_date: "Start",
  maturity_date: "Maturity",
  invested: "Invested",
  current_value: "Current",
  gain: "Gain",
  gain_pct: "Gain %",
  status: "Status",
};

const rowName = (r: RecurringDepositItem) =>
  r.label ? `${r.bank} · ${r.label}` : r.bank;

const kit = createColumnKit<RecurringDepositItem>("rd", labels, rowName);

export const rdConfig: GridConfig<RecurringDepositItem> = {
  type: "rd",
  noun: "recurring deposits",
  searchPlaceholder: "Search recurring deposits…",
  sortKeys: [
    "bank",
    "monthly_instalment",
    "rate",
    "start_date",
    "maturity_date",
    "invested",
    "current_value",
    "gain",
    "gain_pct",
    "status",
  ],
  filters: [
    { kind: "facet", key: "bank", title: "Bank" },
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
    kit.money("monthly_instalment", (r) => r.monthly_instalment),
    kit.number("rate", (r) => r.rate, formatPct),
    kit.date("start_date", (r) => r.start_date),
    kit.date("maturity_date", (r) => r.maturity_date),
    kit.money("invested", (r) => r.invested),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.status(),
    kit.actions(handlers),
  ],
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="rd" record={row} onSaved={onSaved} />
  ),
};
