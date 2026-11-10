import { AssetForm } from "@/components/forms/asset-form";
import { maturityKpi } from "@/components/holding-detail/utils";
import { StalePill } from "@/components/portfolio/stale-pill";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { PF_KIND_LABELS, type PfItem } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  kind: "Type",
  balance: "Balance",
  accrued_interest: "Accrued",
  current_value: "Current value",
  interest_rate: "Rate",
  maturity_date: "Maturity",
};

const rowName = (r: PfItem) => r.name;

const kit = createColumnKit<PfItem>("pf", labels, rowName);

export const pfConfig: GridConfig<PfItem> = {
  type: "pf",
  noun: "PF Accounts",
  searchPlaceholder: "Search PF accounts…",
  sortKeys: [
    "name",
    "kind",
    "balance_date",
    "current_value",
    "interest_rate",
    "maturity_date",
  ],
  filters: [
    { kind: "facet", key: "kind", title: "Type", labels: PF_KIND_LABELS },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "name",
      (r) => r.name,
      () => null,
    ),
    kit.text("kind", (r) => PF_KIND_LABELS[r.kind]),
    kit.display("balance", (r) => (
      <span className="inline-flex items-center gap-2 whitespace-nowrap">
        <span className="num">{formatINR(r.balance)}</span>
        {r.stale ? <StalePill /> : null}
      </span>
    )),
    kit.display("accrued_interest", (r) => (
      <span className="num whitespace-nowrap">
        {formatINR(r.accrued_interest)}
      </span>
    )),
    kit.money("current_value", (r) => r.current_value),
    kit.percent("interest_rate", (r) => r.interest_rate),
    {
      ...kit.date("maturity_date", (r) => r.maturity_date),
      cell: ({ row }) => {
        const r = row.original;
        const shown = r.extended_until
          ? `Extended · till ${formatDate(r.extended_until)}`
          : r.maturity_date
            ? formatDate(r.maturity_date)
            : null;
        return shown ? (
          <span className="num whitespace-nowrap">{shown}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => PF_KIND_LABELS[r.kind],
    kpi: (r) =>
      r.kind === "ppf" && r.extended_until
        ? {
            label: "Maturity",
            value: <span className="num">Extended</span>,
            sub: `till ${formatDate(r.extended_until)}`,
          }
        : r.kind === "ppf"
          ? maturityKpi(r.maturity_date ?? undefined, false)
          : {
            label: "Interest rate",
            value: <span className="num">{formatPct(r.interest_rate)}</span>,
            sub: "per year",
          },
    tenure: (r) => {
      if (r.kind !== "ppf") return null;
      if (r.extended_until) {
        const year = Number(r.extended_until.slice(0, 4)) - 5;
        return {
          start: `${String(year).padStart(4, "0")}${r.extended_until.slice(4)}`,
          end: r.extended_until,
          label: "Current extension block",
        };
      }
      return r.opened_on && r.maturity_date
        ? { start: r.opened_on, end: r.maturity_date }
        : null;
    },
    holding: (r) => [
      { label: "Type", value: PF_KIND_LABELS[r.kind] },
      { label: "Balance", value: formatINR(r.balance), figure: true },
      {
        label: "Accrued interest",
        value: formatINR(r.accrued_interest),
        figure: true,
      },
      { label: "Interest rate", value: formatPct(r.interest_rate), figure: true },
      {
        label: "Total deposited",
        value: r.contributed == null ? null : formatINR(r.contributed),
        figure: true,
      },
      {
        label: "Balance as of",
        value: formatDate(r.balance_date),
        figure: true,
      },
      {
        label: "Opening date",
        value: r.opened_on ? formatDate(r.opened_on) : null,
        figure: true,
      },
      {
        label: "Maturity",
        value:
          r.kind !== "ppf" || !r.maturity_date
            ? null
            : r.extended_until
              ? `Extended · till ${formatDate(r.extended_until)}`
              : formatDate(r.maturity_date),
        figure: true,
      },
    ],
    instrument: () => [],
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="pf" record={row} onSaved={onSaved} />
  ),
};
