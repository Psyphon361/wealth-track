"use client";

import {
  Controller,
  useWatch,
  type Control,
  type FieldValues,
  type Path,
  type PathValue,
  type UseFormSetValue,
} from "react-hook-form";
import { FormError, Label, TextField } from "@/components/forms/fields";
import { useFormDisabled } from "@/components/forms/form-disabled";
import { Field } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { ApiMessage } from "@/lib/api";
import {
  CHOICE_NEW,
  PAID_FROM_INFO,
  destinationOptions,
  effectText,
  type CashAccount,
} from "@/lib/exits";

/**
 * "Where did the money land?": each cash account, a new savings account and spent elsewhere.
 * The host form needs string fields `destination` and `cash_name`. Under the select it says
 * what the choice does to net worth, and how to avoid counting the money twice later.
 */
export function DestinationField<TIn extends FieldValues, TOut>({
  control,
  setValue,
  accounts,
  accountsError,
  amount,
  suggestedName,
}: {
  control: Control<TIn, unknown, TOut>;
  setValue: UseFormSetValue<TIn>;
  /** Null while loading. */
  accounts: CashAccount[] | null;
  accountsError: ApiMessage | null;
  /** The money that moves, or null while it isn't a usable number. */
  amount: number | null;
  /** Prefill for the new account's name, e.g. "HDFC Bank Savings". */
  suggestedName: string;
}) {
  const locked = useFormDisabled();
  const list = accounts ?? [];
  const options = destinationOptions(list);
  const destinationName = "destination" as Path<TIn>;
  const nameField = "cash_name" as Path<TIn>;
  const cashName = useWatch({ control, name: nameField }) as string | undefined;
  const choice = useWatch({ control, name: destinationName }) as string | undefined;

  return (
    <div className="flex flex-col gap-3 sm:col-span-2">
      <Controller
        control={control}
        name={destinationName}
        render={({ field, fieldState }) => {
          const value = String(field.value ?? "");
          const effect = effectText(value, list, amount);
          return (
            <Field data-invalid={fieldState.invalid} className="gap-1.5">
              <Label id="destination" label="Where Did The Money Land?" required />
              <Select
                items={options}
                value={value === "" ? null : value}
                disabled={locked || accounts === null}
                onValueChange={(v) => {
                  const next = v ?? "";
                  field.onChange(next);
                  if (next === CHOICE_NEW && !cashName) {
                    setValue(nameField, suggestedName as PathValue<TIn, Path<TIn>>, {
                      shouldDirty: true,
                    });
                  }
                }}
              >
                <SelectTrigger
                  id="destination"
                  className="w-full"
                  aria-invalid={fieldState.invalid}
                  onBlur={field.onBlur}
                >
                  <SelectValue
                    placeholder={accounts === null ? "Loading Accounts…" : "Choose One"}
                  />
                </SelectTrigger>
                <SelectContent alignItemWithTrigger={false}>
                  {options.map((o) => (
                    <SelectItem key={o.value} value={o.value}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {effect ? (
                <p className="num text-[13.2px] text-muted-foreground">{effect}</p>
              ) : null}
              <p className="text-[13.2px] text-muted-foreground">{PAID_FROM_INFO}</p>
              {accountsError ? (
                <p className="text-[13.2px] text-destructive">
                  {accountsError.message}
                  {accountsError.description ? `. ${accountsError.description}` : ""}
                </p>
              ) : null}
              <FormError error={fieldState.error} />
            </Field>
          );
        }}
      />
      {choice === CHOICE_NEW ? (
        <TextField control={control} name={nameField} label="Account name" required />
      ) : null}
    </div>
  );
}
