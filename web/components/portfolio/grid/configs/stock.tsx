import { AssetForm } from "@/components/forms/asset-form";
import { EXCHANGE_LABELS, type StockItem } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit } from "./shared";

const labels = {
  name: "Name",
  exchange: "Exchange",
  broker: "Broker",
  quantity: "Qty",
  avg_buy_price: "Avg price",
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
    kit.money("invested", (r) => r.invested),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.date("buy_date", (r) => r.buy_date),
    kit.actions(handlers),
  ],
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="stock" record={row} onSaved={onSaved} />
  ),
};
