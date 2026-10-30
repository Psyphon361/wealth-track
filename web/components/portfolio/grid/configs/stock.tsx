import { AssetForm } from "@/components/forms/asset-form";
import {
  formatDate,
  formatINR,
  formatIstDateTime,
  formatPct,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { EXCHANGE_LABELS, type StockItem, type StockMaster } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  exchange: "Exchange",
  broker: "Broker",
  quantity: "Qty",
  avg_buy_price: "Avg price",
  price: "Price",
  invested: "Invested",
  current_value: "Current",
  gain: "Gain",
  gain_pct: "Gain %",
  buy_date: "Buy date",
};

const rowName = (r: StockItem) => r.name;

const kit = createColumnKit<StockItem>("stock", labels, rowName);

export const stockConfig: GridConfig<StockItem> = {
  type: "stock",
  noun: "stocks",
  searchPlaceholder: "Search stocks…",
  sortKeys: [
    "name",
    "exchange",
    "broker",
    "quantity",
    "avg_buy_price",
    "invested",
    "current_value",
    "gain",
    "gain_pct",
    "buy_date",
  ],
  filters: [
    {
      kind: "facet",
      key: "exchange",
      title: "Exchange",
      labels: EXCHANGE_LABELS,
    },
    { kind: "facet", key: "broker", title: "Broker" },
  ],
  columnLabels: labels,
  rowName,
  createColumns: (handlers) => [
    kit.primary(
      "name",
      (r) => r.name,
      (r) => r.symbol,
    ),
    kit.text("exchange", (r) => EXCHANGE_LABELS[r.exchange]),
    kit.text("broker", (r) => r.broker),
    kit.number("quantity", (r) => r.quantity, (n) => String(n)),
    kit.money("avg_buy_price", (r) => r.avg_buy_price),
    kit.display("price", (r) =>
      r.price === null ? (
        <span className="text-muted-foreground">—</span>
      ) : (
        <div className="leading-tight whitespace-nowrap">
          <div className="num">{formatINR(r.price)}</div>
          {r.day_change_pct !== null ? (
            <div
              className={cn(
                "num text-[11px]",
                r.day_change_pct > 0 && "text-gain",
                r.day_change_pct < 0 && "text-loss",
                r.day_change_pct === 0 && "text-muted-foreground",
              )}
            >
              {r.day_change_pct > 0 ? "+" : ""}
              {formatPct(r.day_change_pct)}
            </div>
          ) : null}
        </div>
      ),
    ),
    kit.money("invested", (r) => r.invested),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.date("buy_date", (r) => r.buy_date),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => [r.symbol, EXCHANGE_LABELS[r.exchange]].filter(Boolean).join(" · "),
    kpi: (r) => ({
      label: "Price",
      value:
        r.price === null ? "—" : <span className="num">{formatINR(r.price)}</span>,
      sub:
        r.price !== null && r.day_change_pct !== null ? (
          <span
            className={cn(
              "num",
              r.day_change_pct > 0 && "text-gain",
              r.day_change_pct < 0 && "text-loss",
            )}
          >
            {r.day_change_pct > 0 ? "+" : ""}
            {formatPct(r.day_change_pct)} today
          </span>
        ) : undefined,
    }),
    holding: (r) => [
      { label: "Name", value: r.name },
      { label: "Symbol", value: r.symbol },
      { label: "Exchange", value: EXCHANGE_LABELS[r.exchange] },
      { label: "Broker", value: r.broker },
      { label: "Quantity", value: String(r.quantity), figure: true },
      { label: "Avg buy price", value: formatINR(r.avg_buy_price), figure: true },
      { label: "Purchase date", value: formatDate(r.buy_date), figure: true },
    ],
    instrument: (m, r) => {
      const s = m as StockMaster;
      return [
        { label: "ISIN", value: s.isin, figure: true },
        { label: "NSE symbol", value: s.nse_symbol },
        { label: "BSE symbol", value: s.bse_symbol ?? s.bse_code },
        {
          label: "Price date",
          value: r.price_time ? formatIstDateTime(r.price_time) : null,
          figure: true,
        },
      ];
    },
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="stock" record={row} onSaved={onSaved} />
  ),
};
