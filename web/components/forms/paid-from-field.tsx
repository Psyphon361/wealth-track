"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  useWatch,
  type Control,
  type FieldValues,
  type Path,
  type PathValue,
  type UseFormSetValue,
} from "react-hook-form";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCashAccounts } from "@/components/exits/use-cash-accounts";
import {
  OUTSIDE_MONEY_LABEL,
  PAID_FROM_HELPER,
  PAID_FROM_LABEL,
  REINVEST_AMOUNT_FIELD,
  REINVEST_DATE_FIELD,
  accountLabel,
  paidFromAmount,
  paidFromBody,
  paidFromEditLine,
  paidFromEffect,
  paidFromError,
  paidFromReadOnly,
  recordPaidFrom,
  reinvestHint,
  reinvestNote,
  type PaidFromAccount,
  type PaidFromBody,
  type PaidFromRecord,
} from "@/lib/paid-from";
import type { ReinvestPrefill } from "@/lib/reinvest";
import type { AssetType } from "@/lib/types";
import { FormError } from "./fields";
import { useFormDisabled } from "./form-disabled";

const OUTSIDE = "outside";
/** State shared by the form plumbing: the field, the submit guard and the payload. */
export interface PaidFromState {
  type: AssetType;
  /** The Edit dialog: no Select, only a read-only line when the record has one. */
  editing: boolean;
  readOnly: PaidFromRecord | null;
  cashId: number | null;
  setCashId: (id: number | null) => void;
  accounts: PaidFromAccount[] | null;
  /** Accounts failed to load: only outside money is offered. */
  failed: boolean;
  amount: number | null;
  /** Live validation message (or one the API returned), else null. */
  error: string | null;
  /** Spread into the create payload. */
  body: { paid_from: PaidFromBody } | Record<string, never>;
  reinvest: ReinvestPrefill | null;
  /** Hint line when the type has no single amount field to prefill. */
  reinvestHint: string | null;
  /** Hand API field issues here; `cash_id` ones show under the field. */
  applyIssues: (issues: { field: string; message: string }[]) => void;
}

export function usePaidFrom<TIn extends FieldValues, TOut>({
  type,
  record,
  control,
  setValue,
  reinvest,
}: {
  type: AssetType;
  record?: { id: number; paid_from?: PaidFromRecord | null };
  control: Control<TIn, unknown, TOut>;
  setValue: UseFormSetValue<TIn>;
  reinvest?: ReinvestPrefill | null;
}): PaidFromState {
  const editing = !!record;
  const values = useWatch({ control }) as Record<string, unknown>;
  const [cashId, setCashIdState] = useState<number | null>(
    !editing && reinvest ? reinvest.cash_id : null,
  );
  const [serverError, setServerError] = useState<string | null>(null);
  const { accounts: fetched, error: loadError } = useCashAccounts();
  const failed = loadError !== null;
  const fromExitId = !editing && reinvest ? reinvest.from_exit_id : undefined;

  // Apply the reinvest prefill once, when the form opens.
  const applied = useRef(false);
  useEffect(() => {
    if (applied.current || editing || !reinvest) return;
    applied.current = true;
    const amountField = REINVEST_AMOUNT_FIELD[type];
    if (amountField) {
      setValue(
        amountField as Path<TIn>,
        String(reinvest.amount) as PathValue<TIn, Path<TIn>>,
      );
    }
    setValue(
      REINVEST_DATE_FIELD[type] as Path<TIn>,
      reinvest.date as PathValue<TIn, Path<TIn>>,
    );
  }, [editing, reinvest, type, setValue]);

  // A cash account can't pay for itself.
  const accounts = useMemo(
    () =>
      fetched
        ? fetched.filter((a) => !(type === "cash" && a.id === record?.id))
        : null,
    [fetched, type, record?.id],
  );

  const setCashId = useCallback((id: number | null) => {
    setCashIdState(id);
    setServerError(null);
  }, []);

  const amount = paidFromAmount(type, values);
  const error =
    serverError ?? paidFromError(type, cashId, accounts, amount);

  const applyIssues = useCallback(
    (issues: { field: string; message: string }[]) => {
      const i = issues.find((x) => x.field === "cash_id");
      if (i) setServerError(i.message);
    },
    [],
  );

  return {
    type,
    editing,
    readOnly: editing ? recordPaidFrom(record) : null,
    cashId,
    setCashId,
    accounts,
    failed,
    amount,
    error,
    body: editing ? {} : paidFromBody(cashId, fromExitId),
    reinvest: !editing && reinvest ? reinvest : null,
    reinvestHint:
      !editing && reinvest && !REINVEST_AMOUNT_FIELD[type]
        ? reinvestHint(reinvest)
        : null,
    applyIssues,
  };
}

/** Small note above a reinvest form: "Reinvesting ₹1,07,186 from HDFC Savings." */
export function ReinvestNote({ state }: { state: PaidFromState }) {
  if (!state.reinvest) return null;
  return (
    <div className="flex flex-col gap-0.5 rounded-md border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground sm:col-span-2">
      <span>{reinvestNote(state.reinvest)}</span>
      {state.reinvestHint ? <span className="num">{state.reinvestHint}</span> : null}
    </div>
  );
}

export function PaidFromField({ state }: { state: PaidFromState }) {
  const locked = useFormDisabled();

  if (state.editing) {
    if (!state.readOnly) return null;
    const account = state.accounts?.find(
      (a) => a.id === state.readOnly?.cash_holding_id,
    );
    const line = paidFromEditLine(
      state.readOnly,
      account ? account.balance : null,
      state.amount,
    );
    return (
      <div className="flex flex-col gap-0.5 sm:col-span-2">
        <p className="text-xs text-muted-foreground">
          {paidFromReadOnly(state.readOnly)}
        </p>
        {line ? (
          <p
            className={
              line.tone === "error"
                ? "num text-xs text-loss"
                : line.tone === "effect"
                  ? "num text-xs text-foreground"
                  : "text-xs text-muted-foreground"
            }
          >
            {line.text}
          </p>
        ) : null}
      </div>
    );
  }

  const loading = state.accounts === null && !state.failed;
  const chosen = state.accounts?.find((a) => a.id === state.cashId) ?? null;
  const items = [
    { value: OUTSIDE, label: OUTSIDE_MONEY_LABEL },
    ...(state.accounts ?? []).map((a) => ({
      value: String(a.id),
      label: accountLabel(a),
    })),
  ];
  // While accounts load, still name the account a reinvest chose.
  if (loading && state.cashId !== null && state.reinvest) {
    items.push({ value: String(state.cashId), label: state.reinvest.cash_name });
  }
  const value = state.cashId === null ? OUTSIDE : String(state.cashId);

  return (
    <Field data-invalid={!!state.error} className="gap-1.5 sm:col-span-2">
      <FieldLabel
        htmlFor="paid_from"
        className="text-xs font-normal text-muted-foreground"
      >
        {PAID_FROM_LABEL}
      </FieldLabel>
      <Select
        items={items}
        value={value}
        disabled={locked || loading}
        onValueChange={(v) =>
          state.setCashId(v === null || v === OUTSIDE ? null : Number(v))
        }
      >
        <SelectTrigger
          id="paid_from"
          className="w-full"
          aria-invalid={!!state.error}
        >
          {loading && state.cashId === null ? (
            <span className="text-muted-foreground">Loading Accounts…</span>
          ) : (
            <SelectValue />
          )}
        </SelectTrigger>
        <SelectContent alignItemWithTrigger={false}>
          {items.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-[13.2px] text-muted-foreground">{PAID_FROM_HELPER}</p>
      {chosen && state.amount !== null ? (
        <p className="num text-xs text-foreground">
          {paidFromEffect(chosen, state.amount)}
        </p>
      ) : null}
      <FormError error={state.error ? { message: state.error } : undefined} />
    </Field>
  );
}
