"use client";

import {
  Controller,
  type Control,
  type FieldValues,
  type Path,
} from "react-hook-form";
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
    <FieldLabel htmlFor={id}>
      {label}
      {required ? null : (
        <span className="font-normal text-muted-foreground">(optional)</span>
      )}
    </FieldLabel>
  );
}

export function TextField<TIn extends FieldValues, TOut>({
  control,
  name,
  label,
  required,
  inputMode,
  type = "text",
}: FieldProps<TIn, TOut> & {
  inputMode?: "decimal" | "numeric";
  type?: "text" | "date";
}) {
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => (
        <Field data-invalid={fieldState.invalid}>
          <Label id={name} label={label} required={required} />
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
          />
          <FieldError errors={[fieldState.error]} />
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
          <FieldError errors={[fieldState.error]} />
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
          />
          <FieldError errors={[fieldState.error]} />
        </Field>
      )}
    />
  );
}
