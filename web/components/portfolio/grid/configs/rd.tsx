import { AssetForm } from "@/components/forms/asset-form";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { formatTenure, maturityKpi } from "@/components/holding-detail/utils";
import {
  COMPOUNDING_LABELS,
  FD_ISSUER_CATEGORY_LABELS,
  type FdIssuer,
  type RecurringDepositItem,
} from "@/lib/types";
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
  detail: {
    subtitle: (r) =>
      `${formatPct(r.rate)} · ${COMPOUNDING_LABELS[r.compounding]}`,
    kpi: (r) => maturityKpi(r.maturity_date, r.status === "matured"),
    tenure: (r) =>
      r.maturity_date ? { start: r.start_date, end: r.maturity_date } : null,
    holding: (r) => [
      { label: "Bank", value: r.bank },
      { label: "Label", value: r.label },
      {
        label: "Monthly instalment",
        value: formatINR(r.monthly_instalment),
        figure: true,
      },
      { label: "Interest rate", value: formatPct(r.rate), figure: true },
      { label: "Compounding", value: COMPOUNDING_LABELS[r.compounding] },
      { label: "Start date", value: formatDate(r.start_date), figure: true },
      {
        label: "Tenure",
        value: formatTenure(r.tenure_years, r.tenure_months, r.tenure_days),
      },
      {
        label: "Maturity date",
        value: r.maturity_date ? formatDate(r.maturity_date) : null,
        figure: true,
      },
    ],
    instrument: (m) => {
      const i = m as FdIssuer;
      return [
        { label: "Issuer type", value: FD_ISSUER_CATEGORY_LABELS[i.category] },
        {
          label: "DICGC insured",
          value: i.dicgc_insured == null ? null : i.dicgc_insured ? "Yes" : "No",
        },
      ];
    },
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="rd" record={row} onSaved={onSaved} />
  ),
};
