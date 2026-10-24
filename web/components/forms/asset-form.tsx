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

export type AssetFormProps =
  | { type: "fd"; record?: FixedDeposit; onSaved?: (r: FixedDeposit) => void }
  | {
      type: "rd";
      record?: RecurringDeposit;
      onSaved?: (r: RecurringDeposit) => void;
    }
  | { type: "stock"; record?: Stock; onSaved?: (r: Stock) => void }
  | { type: "bond"; record?: Bond; onSaved?: (r: Bond) => void }
  | { type: "mf"; record?: MutualFund; onSaved?: (r: MutualFund) => void };

export type { AssetType };

/**
 * Creates (POST) when no record is given, otherwise edits (PUT) the record.
 * Layout-neutral: renders only the form.
 */
export function AssetForm(props: AssetFormProps) {
  switch (props.type) {
    case "fd":
      return <FdForm record={props.record} onSaved={props.onSaved} />;
    case "rd":
      return <RdForm record={props.record} onSaved={props.onSaved} />;
    case "stock":
      return <StockForm record={props.record} onSaved={props.onSaved} />;
    case "bond":
      return <BondForm record={props.record} onSaved={props.onSaved} />;
    case "mf":
      return <MfForm record={props.record} onSaved={props.onSaved} />;
  }
}
