import type { ReactNode } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  BOND_TYPE_LABELS,
  COMPOUNDING_LABELS,
  MF_CATEGORY_LABELS,
  type Bond,
  type ComputedFields,
  type FixedDeposit,
  type MutualFund,
  type PortfolioItem,
  type RecurringDeposit,
  type Stock,
} from "@/lib/types";

export interface Column<T> {
  header: string;
  align?: "right";
  cell: (r: T) => ReactNode;
}

export type Row<T> = T & ComputedFields;

export function gainTone(gain: number): string {
  return gain > 0 ? "text-gain" : gain < 0 ? "text-loss" : "text-foreground";
}

export function GainCell({ gain, pct }: { gain: number; pct: number }) {
  const sign = gain > 0 ? "+" : "";
  return (
    <span
      className={cn(
        "num inline-flex items-baseline gap-1.5 whitespace-nowrap",
        gainTone(gain),
      )}
    >
      {sign}
      {formatINR(gain)}
      <span className="flex items-center gap-0.5 text-[11px] opacity-80">
        {gain > 0 ? (
          <TrendingUp className="size-3" aria-hidden />
        ) : gain < 0 ? (
          <TrendingDown className="size-3" aria-hidden />
        ) : null}
        {sign}
        {formatPct(pct)}
      </span>
    </span>
  );
}

function Main({ main, sub }: { main: string; sub?: string | null }) {
  return (
    <div className="min-w-32 leading-tight">
      <div className="font-medium">{main}</div>
      {sub ? (
        <div className="text-[11px] text-muted-foreground">{sub}</div>
      ) : null}
    </div>
  );
}

function StatusBadge({ status }: { status: ComputedFields["status"] }) {
  return status === "active" ? (
    <Badge variant="outline" className="font-normal">
      Active
    </Badge>
  ) : (
    <Badge variant="secondary" className="font-normal text-muted-foreground">
      Matured
    </Badge>
  );
}

const nowrap = (s: string) => (
  <span className="num whitespace-nowrap">{s}</span>
);

function money<T extends ComputedFields>(
  currentSub?: (r: T) => ReactNode,
): Column<T>[] {
  return [
    { header: "Invested", align: "right", cell: (r) => nowrap(formatINR(r.invested)) },
    {
      header: "Current",
      align: "right",
      cell: (r) =>
        currentSub ? (
          <div className="leading-tight">
            {nowrap(formatINR(r.current_value))}
            {currentSub(r)}
          </div>
        ) : (
          nowrap(formatINR(r.current_value))
        ),
    },
    {
      header: "Gain",
      align: "right",
      cell: (r) => <GainCell gain={r.gain} pct={r.gain_pct} />,
    },
  ];
}

function status<T extends ComputedFields>(): Column<T> {
  return { header: "Status", cell: (r) => <StatusBadge status={r.status} /> };
}

function fdBankCell(r: Row<FixedDeposit>) {
  return (
    <div className="min-w-32 leading-tight">
      <div className="font-medium">{r.bank}</div>
      {r.label ? (
        <div className="text-[11px] text-muted-foreground">{r.label}</div>
      ) : null}
      {r.payout_type === "payout" ? (
        <div className="text-[11px] text-muted-foreground">
          Payout · {COMPOUNDING_LABELS[r.compounding]}
        </div>
      ) : null}
    </div>
  );
}

export const fdColumns: Column<Row<FixedDeposit>>[] = [
  { header: "Bank", cell: fdBankCell },
  { header: "Rate", align: "right", cell: (r) => nowrap(formatPct(r.rate)) },
  { header: "Start", cell: (r) => nowrap(formatDate(r.start_date)) },
  {
    header: "Maturity",
    cell: (r) => (r.maturity_date ? nowrap(formatDate(r.maturity_date)) : "—"),
  },
  ...money<Row<FixedDeposit>>((r) =>
    r.payout_type === "payout" && r.interest_received != null ? (
      <div className="num whitespace-nowrap text-[11px] text-muted-foreground">
        Interest received {formatINR(r.interest_received)}
      </div>
    ) : null,
  ),
  status<Row<FixedDeposit>>(),
];

export const rdColumns: Column<Row<RecurringDeposit>>[] = [
  { header: "Bank", cell: (r) => <Main main={r.bank} sub={r.label} /> },
  {
    header: "Monthly instalment",
    align: "right",
    cell: (r) => nowrap(formatINR(r.monthly_instalment)),
  },
  { header: "Rate", align: "right", cell: (r) => nowrap(formatPct(r.rate)) },
  {
    header: "Maturity",
    cell: (r) => (r.maturity_date ? nowrap(formatDate(r.maturity_date)) : "—"),
  },
  ...money<Row<RecurringDeposit>>(),
  status<Row<RecurringDeposit>>(),
];

export const stockColumns: Column<Row<Stock>>[] = [
  {
    header: "Name",
    cell: (r) => (
      <Main
        main={r.name}
        sub={[r.symbol, r.exchange].filter(Boolean).join(" · ")}
      />
    ),
  },
  { header: "Qty", align: "right", cell: (r) => nowrap(String(r.quantity)) },
  {
    header: "Avg price",
    align: "right",
    cell: (r) => nowrap(formatINR(r.avg_buy_price)),
  },
  { header: "Buy date", cell: (r) => nowrap(formatDate(r.buy_date)) },
  ...money<Row<Stock>>(),
];

export const bondColumns: Column<Row<Bond>>[] = [
  { header: "Name", cell: (r) => <Main main={r.name} sub={r.issuer} /> },
  { header: "Type", cell: (r) => BOND_TYPE_LABELS[r.bond_type] ?? r.bond_type },
  {
    header: "Qty",
    align: "right",
    cell: (r) => (
      <div className="leading-tight">
        {nowrap(String(r.quantity))}
        <div className="num whitespace-nowrap text-[11px] text-muted-foreground">
          FV {r.face_value == null ? "—" : formatINR(r.face_value)}
        </div>
      </div>
    ),
  },
  { header: "YTM", align: "right", cell: (r) => nowrap(formatPct(r.ytm)) },
  { header: "Maturity", cell: (r) => nowrap(formatDate(r.maturity_date)) },
  ...money<Row<Bond>>(),
  status<Row<Bond>>(),
];

export const mfColumns: Column<Row<MutualFund>>[] = [
  { header: "Scheme", cell: (r) => <Main main={r.scheme_name} sub={r.platform} /> },
  {
    header: "Category",
    cell: (r) => MF_CATEGORY_LABELS[r.category] ?? r.category,
  },
  { header: "Units", align: "right", cell: (r) => nowrap(String(r.units)) },
  { header: "Avg NAV", align: "right", cell: (r) => nowrap(formatINR(r.avg_nav)) },
  ...money<Row<MutualFund>>(),
];

export function itemName(item: PortfolioItem): string {
  if ("scheme_name" in item) return item.scheme_name;
  if ("bank" in item) return item.label ? `${item.bank} (${item.label})` : item.bank;
  return item.name;
}
