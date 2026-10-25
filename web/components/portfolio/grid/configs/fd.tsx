import { AssetForm } from "@/components/forms/asset-form";
import { Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  COMPOUNDING_LABELS,
  PAYOUT_TYPE_LABELS,
  type FixedDepositItem,
} from "@/lib/types";
import type { GridConfig } from "../types";
import { GainCell, gainTone } from "../gain-cell";
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
    {
      ...kit.money("current_value", (r) => r.current_value),
      cell: ({ row }) => {
        const r = row.original;
        return (
          <span className="num inline-flex items-center gap-1 whitespace-nowrap">
            {formatINR(r.current_value)}
            {r.payout_type === "payout" ? (
              <Tooltip>
                <TooltipTrigger
                  render={<span className="text-muted-foreground" />}
                >
                  <Info className="size-3" aria-label="Principal only" />
                </TooltipTrigger>
                <TooltipContent>
                  Principal only. Interest is paid out to your bank.
                </TooltipContent>
              </Tooltip>
            ) : null}
          </span>
        );
      },
    },
    {
      ...kit.gain(),
      cell: ({ row }) => {
        const r = row.original;
        const cell = <GainCell gain={r.gain} pct={r.gain_pct} showPct={false} />;
        if (r.payout_type !== "payout") return cell;
        return (
          <div className="flex flex-col items-end text-right leading-tight">
            {cell}
            <span className="text-[11px] text-muted-foreground">
              interest paid
            </span>
          </div>
        );
      },
    },
    {
      ...kit.gainPct(),
      cell: ({ row }) => {
        const r = row.original;
        return (
          <div className="flex flex-col items-end text-right leading-tight">
            <span className={cn("num whitespace-nowrap", gainTone(r.gain))}>
              {r.gain > 0 ? "+" : ""}
              {formatPct(r.gain_pct)}
            </span>
            {r.payout_type === "payout" ? (
              <span className="text-[11px] text-muted-foreground">
                over tenure
              </span>
            ) : null}
          </div>
        );
      },
    },
    kit.status(),
    kit.actions(handlers),
  ],
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="fd" record={row} onSaved={onSaved} />
  ),
};
