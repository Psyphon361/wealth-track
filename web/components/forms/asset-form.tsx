"use client";

import type {
  AssetType,
  Bond,
  FixedDeposit,
  MutualFund,
  RecurringDeposit,
  Stock,
} from "@/lib/types";
import { BondForm } from "./bond-form";
import { FdForm } from "./fd-form";
import { MfForm } from "./mf-form";
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
  | ({ type: "mf" } & Common<MutualFund>);

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
  }
}
