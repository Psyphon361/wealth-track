"use client";

import type {
  AssetType,
  Bond,
  Cash,
  FixedDeposit,
  FixedDepositInput,
  Gold,
  MutualFund,
  Nps,
  Other,
  Pf,
  RecurringDeposit,
  RecurringDepositInput,
  Stock,
} from "@/lib/types";
import type { ReinvestPrefill } from "@/lib/reinvest";
import { BondForm } from "./bond-form";
import { CashForm } from "./cash-form";
import { FdForm } from "./fd-form";
import { GoldForm } from "./gold-form";
import { MfForm } from "./mf-form";
import { NpsForm } from "./nps-form";
import { OtherForm } from "./other-form";
import { PfForm } from "./pf-form";
import { RdForm } from "./rd-form";
import { StockForm } from "./stock-form";

type Common<R> = {
  record?: R;
  onSaved?: (r: R) => void;
  onCancel?: () => void;
  /** One-shot prefill from "Reinvest" (create only). */
  reinvest?: ReinvestPrefill | null;
};

/** Prefill a new record, and optionally take the payload instead of saving it. */
type Prefill<TInput> = {
  defaults?: Partial<TInput>;
  submit?: (payload: TInput) => Promise<void> | void;
  submitLabel?: string;
};

export type AssetFormProps =
  | ({ type: "fd" } & Common<FixedDeposit> & Prefill<FixedDepositInput>)
  | ({ type: "rd" } & Common<RecurringDeposit> & Prefill<RecurringDepositInput>)
  | ({ type: "stock" } & Common<Stock>)
  | ({ type: "bond" } & Common<Bond>)
  | ({ type: "mf" } & Common<MutualFund>)
  | ({ type: "gold" } & Common<Gold>)
  | ({ type: "cash" } & Common<Cash>)
  | ({ type: "pf" } & Common<Pf>)
  | ({ type: "nps" } & Common<Nps>)
  | ({ type: "other" } & Common<Other>);

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
          defaults={props.defaults}
          submit={props.submit}
          submitLabel={props.submitLabel}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
          reinvest={props.reinvest}
        />
      );
    case "rd":
      return (
        <RdForm
          record={props.record}
          defaults={props.defaults}
          submit={props.submit}
          submitLabel={props.submitLabel}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
          reinvest={props.reinvest}
        />
      );
    case "stock":
      return (
        <StockForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "bond":
      return (
        <BondForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "mf":
      return (
        <MfForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "gold":
      return (
        <GoldForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "cash":
      return (
        <CashForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "pf":
      return (
        <PfForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "nps":
      return (
        <NpsForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
    case "other":
      return (
        <OtherForm
          reinvest={props.reinvest}
          record={props.record}
          onSaved={props.onSaved}
          onCancel={props.onCancel}
        />
      );
  }
}
