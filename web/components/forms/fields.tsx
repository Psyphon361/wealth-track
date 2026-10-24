"use client";

import {
  Controller,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
import { cn } from "cn";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export type Option = { value: string; label: string };

export function toOptions<K extends string>(
  labels: Record<K, string>,
): Option[] {
  return (Object.keys(labels) as K[]).map((value) => ({
    value,
    label: labels[value],
  }));
}

interface FieldProps<TIn extends FieldValues, TOut> {
  control: Control<TIn, unknown, TOut>;
  name: Path<TIn>;
  label: string;
  required?: boolean;
}

function Label({
  id,
  label,
  required,
}: {
  id: string;
  label: string;
  required?: boolean;
}) {
  return (
    <FieldLabel
      htmlFor={id}
      className="text-xs font-normal text-muted-foreground"
    >
      {label}
      {required ? null : (
        <span className="text-[10px] tracking-wide text-muted-foreground/60 uppercase">
          optional
        </span>
      )}
    </FieldLabel>
  );
}

export function FormError({
  error,
}: {
  error: { message?: string } | undefined;
}) {
  return <FieldError errors={[error]} className="text-xs text-destructive" />;
}

export function TextField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
  inputMode,
  type = "text",
  adornment,
}: FieldProps<TIn, TOut> & {
  inputMode?: "decimal" | "numeric";
  type?: "text" | "date";
  adornment?: "₹" | "%";
}) {
  const numeric = inputMode !== undefined;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label={label} required={required} />
          <div className="relative">
            <Input
              id={name}
              type={type}
              inputMode={inputMode}
              name={field.name}
              ref={field.ref}
              onBlur={field.onBlur}
              onChange={field.onChange}
              value={String(field.value ?? "")}
              aria-invalid={fieldState.invalid}
              className={cn(
                numeric && "num text-right",
                adornment === "₹" && "pl-6",
                adornment === "%" && "pr-6",
              )}
            />
            {adornment ? (
              <span
                aria-hidden
                className={cn(
                  "pointer-events-none absolute top-1/2 -translate-y-1/2 text-xs text-muted-foreground",
                  adornment === "₹" ? "left-2.5" : "right-2.5",
                )}
              >
                {adornment}
              </span>
            ) : null}
          </div>
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}

export function SelectField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
  options,
}: FieldProps<TIn, TOut> & { options: Option[] }) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label={label} required={required} />
          <Select
            items={options}
            value={String(field.value ?? "")}
            onValueChange={(v) => field.onChange(v ?? "")}
          >
            <SelectTrigger
              id={name}
              className="w-full"
              aria-invalid={fieldState.invalid}
              onBlur={field.onBlur}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}

export function NotesField<TIn extends FieldValues, TOut>({
  control,
  name,
}: Pick<FieldProps<TIn, TOut>, "control" | "name">) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label="Notes" />
          <Textarea
            id={name}
            name={field.name}
            ref={field.ref}
            onBlur={field.onBlur}
            onChange={field.onChange}
            value={String(field.value ?? "")}
            aria-invalid={fieldState.invalid}
            rows={2}
          />
          <FormError error={fieldState.error} />
        </Field>
      )}
    />
  );
}
