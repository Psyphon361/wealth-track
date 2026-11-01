"use client";

import type {
  AssetType,
  Bond,
  Cash,
  FixedDeposit,
  Gold,
  MutualFund,
  Pf,
  RecurringDeposit,
  Stock,
} from "@/lib/types";
import { BondForm } from "./bond-form";
import { CashForm } from "./cash-form";
import { FdForm } from "./fd-form";
import { GoldForm } from "./gold-form";
import { MfForm } from "./mf-form";
import { PfForm } from "./pf-form";
import { RdForm } from "./rd-form";
import { StockForm } from "./stock-form";

type Common<R> = {
  record?: R;
  onSaved?: (r: R) => void;
  onCancel?: () => void;
};

export type AssetFormProps =
  | ({ type: "fd" } & Common<FixedDeposit>)
  | ({ type: "rd" } & Common<RecurringDeposit>)
  | ({ type: "stock" } & Common<Stock>)
  | ({ type: "bond" } & Common<Bond>)
  | ({ type: "mf" } & Common<MutualFund>)
  | ({ type: "gold" } & Common<Gold>)
  | ({ type: "cash" } & Common<Cash>)
  | ({ type: "pf" } & Common<Pf>);

export type { AssetType };

/**
 * Creates (POST) when no record is given, otherwise edits (PUT) the record.
 * Layout-neutral: renders only the form.
 */
export function AssetForm(props: AssetFormProps) {
  switch (props.type) {
    case "fd":
      return (
        <FdForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "rd":
      return (
        <RdForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "stock":
      return (
        <StockForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "bond":
      return (
        <BondForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "mf":
      return (
        <MfForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "gold":
      return (
        <GoldForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "cash":
      return (
        <CashForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "pf":
      return (
        <PfForm
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
  }
}
