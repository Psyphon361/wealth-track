import { AssetForm } from "@/components/forms/asset-form";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { maturityKpi } from "@/components/holding-detail/utils";
import { BOND_TYPE_LABELS, type BondItem, type BondMaster } from "@/lib/types";
import type { GridConfig } from "../types";
import { createColumnKit, STATUS_LABELS } from "./shared";

const labels = {
  name: "Name",
  issuer: "Issuer",
  bond_type: "Type",
  platform: "Platform",
  quantity: "Qty",
  face_value: "Face value",
  purchase_price: "Price",
  ytm: "YTM",
  purchase_date: "Purchase",
  maturity_date: "Maturity",
  invested: "Invested",
  current_value: "Current",
  gain: "Gain",
  gain_pct: "Gain %",
  status: "Status",
};

const rowName = (r: BondItem) => r.name;

const kit = createColumnKit<BondItem>("bond", labels, rowName);

export const bondConfig: GridConfig<BondItem> = {
  type: "bond",
  noun: "bonds",
  searchPlaceholder: "Search bonds…",
  sortKeys: [
    "name",
    "issuer",
    "bond_type",
    "platform",
    "quantity",
    "face_value",
    "purchase_price",
    "ytm",
    "purchase_date",
    "maturity_date",
    "invested",
    "current_value",
    "gain",
    "gain_pct",
    "status",
  ],
  filters: [
    {
      kind: "facet",
      key: "bond_type",
      title: "Type",
      labels: BOND_TYPE_LABELS,
    },
    { kind: "facet", key: "issuer", title: "Issuer" },
    { kind: "facet", key: "platform", title: "Platform" },
    { kind: "facet", key: "status", title: "Status", labels: STATUS_LABELS },
    { kind: "range", title: "YTM", minKey: "ytm_min", maxKey: "ytm_max" },
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
      "name",
      (r) => r.name,
      (r) => r.isin,
    ),
    kit.text("issuer", (r) => r.issuer),
    kit.text("bond_type", (r) => BOND_TYPE_LABELS[r.bond_type]),
    kit.text("platform", (r) => r.platform),
    kit.number("quantity", (r) => r.quantity, (n) => String(n)),
    kit.text(
      "face_value",
      (r) => (r.face_value === null ? null : formatINR(r.face_value)),
      (r) =>
        r.face_value === null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className="num whitespace-nowrap">
            {formatINR(r.face_value)}
          </span>
        ),
    ),
    kit.money("purchase_price", (r) => r.purchase_price),
    kit.number("ytm", (r) => r.ytm, formatPct),
    kit.date("purchase_date", (r) => r.purchase_date),
    kit.date("maturity_date", (r) => r.maturity_date),
    kit.money("invested", (r) => r.invested),
    kit.money("current_value", (r) => r.current_value),
    kit.gain(),
    kit.gainPct(),
    kit.status(),
    kit.actions(handlers),
  ],
  detail: {
    subtitle: (r) => [r.isin, BOND_TYPE_LABELS[r.bond_type]].filter(Boolean).join(" · "),
    kpi: (r) => maturityKpi(r.maturity_date, r.status === "matured"),
    tenure: (r) => ({ start: r.purchase_date, end: r.maturity_date }),
    holding: (r) => [
      { label: "Name", value: r.name },
      { label: "ISIN", value: r.isin, figure: true },
      { label: "Issuer", value: r.issuer },
      { label: "Type", value: BOND_TYPE_LABELS[r.bond_type] },
      { label: "Platform", value: r.platform },
      { label: "Quantity", value: String(r.quantity), figure: true },
      {
        label: "Purchase price per unit",
        value: formatINR(r.purchase_price),
        figure: true,
      },
      { label: "Total invested", value: formatINR(r.invested), figure: true },
      { label: "YTM", value: formatPct(r.ytm), figure: true },
      { label: "Purchase date", value: formatDate(r.purchase_date), figure: true },
      { label: "Maturity date", value: formatDate(r.maturity_date), figure: true },
    ],
    instrument: (m) => {
      const b = m as BondMaster;
      return [
        {
          label: "Coupon rate",
          value: b.coupon_rate == null ? null : formatPct(b.coupon_rate),
          figure: true,
        },
        { label: "Coupon type", value: b.coupon_type },
        { label: "Interest frequency", value: b.interest_frequency },
        {
          label: "Rating",
          value: b.rating
            ? b.rating_agency
              ? `${b.rating} (${b.rating_agency})`
              : b.rating
            : null,
        },
        {
          label: "Face value",
          value: b.face_value == null ? null : formatINR(b.face_value),
          figure: true,
        },
        {
          label: "Issue date",
          value: b.issue_date ? formatDate(b.issue_date) : null,
          figure: true,
        },
      ];
    },
  },
  renderEditForm: (row, onSaved) => (
    <AssetForm key={row.id} type="bond" record={row} onSaved={onSaved} />
  ),
};
