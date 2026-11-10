"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import type { z } from "zod";
import { DateField, TextField } from "@/components/forms/fields";
import { FormBusyContext } from "@/components/forms/form-disabled";
import { FormShell } from "@/components/forms/form-shell";
import {
  cashUpdateSchema,
  moneyUpdateSchema,
  npsUpdateSchema,
  todayISO,
} from "@/components/forms/schema";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiPost } from "@/lib/api";
import { markHoldingsChanged } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { notify } from "@/lib/notify";
import type { AssetType, HoldingRow } from "@/lib/types";
import {
  amountBody,
  amountDefaults,
  amountLabel,
  currentFigureText,
  isUpdateValueType,
  npsBody,
  npsDefaults,
  updateValueLabel,
  type UpdateValueRow,
} from "@/lib/update-value";

/** Quick refresh of the figure that goes stale (balance, value or NPS units). */
export function UpdateValueDialog({
  type,
  row,
  name,
  onClose,
  onSaved,
}: {
  type: AssetType;
  row: HoldingRow | null;
  name: string;
  onClose: () => void;
  onSaved?: () => void;
}) {
  // True while the form inside is saving: the dialog can't be dismissed then.
  const [busy, setBusy] = useState(false);
  const label = updateValueLabel(type);
  return (
    <Dialog
      open={row !== null && label !== null}
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
          <DialogDescription>{name}</DialogDescription>
        </DialogHeader>
        <FormBusyContext.Provider value={setBusy}>
          {row && isUpdateValueType(type) ? (
            type === "nps" ? (
              <NpsUpdateForm
                key={row.id}
                id={row.id}
                row={row as unknown as UpdateValueRow}
                onClose={onClose}
                onSaved={onSaved}
              />
            ) : (
              <AmountUpdateForm
                key={row.id}
                type={type}
                id={row.id}
                row={row as unknown as UpdateValueRow}
                onClose={onClose}
                onSaved={onSaved}
              />
            )
          ) : null}
        </FormBusyContext.Provider>
      </DialogContent>
    </Dialog>
  );
}

/** POST the body, then refresh everything that shows holdings. */
function useUpdateValue(
  type: AssetType,
  id: number,
  onClose: () => void,
  onSaved?: () => void,
) {
  const [saving, setSaving] = useState(false);
  async function save(body: unknown) {
    setSaving(true);
    try {
      const res = await apiPost<Partial<{ message: string; description: string }>>(
        `/assets/${type}/${id}/update-value`,
        body,
      );
      invalidateNetWorth();
      markHoldingsChanged(type, false);
      notify.success(res);
      onClose();
      onSaved?.();
    } catch (e) {
      notify.error(e);
    } finally {
      setSaving(false);
    }
  }
  return { saving, save };
}

type AmountIn = z.input<typeof cashUpdateSchema>;
type AmountOut = z.output<typeof cashUpdateSchema>;

function AmountUpdateForm({
  type,
  id,
  row,
  onClose,
  onSaved,
}: {
  type: "cash" | "pf" | "other";
  id: number;
  row: UpdateValueRow;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const today = todayISO();
  const { control, handleSubmit } = useForm<AmountIn, unknown, AmountOut>({
    resolver: zodResolver(type === "cash" ? cashUpdateSchema : moneyUpdateSchema),
    defaultValues: amountDefaults(type, row, today),
  });
  const { saving, save } = useUpdateValue(type, id, onClose, onSaved);
  const onSubmit = handleSubmit((v) => save(amountBody(type, v.amount, v.date)));
  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing
      onCancel={onClose}
      submitLabel="Save"
    >
      <TextField
        control={control}
        name="amount"
        label={amountLabel(type)}
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        hint={currentFigureText(type, row)}
        required
      />
      <DateField control={control} name="date" label="As Of" maxDate={today} required />
    </FormShell>
  );
}

type NpsIn = z.input<typeof npsUpdateSchema>;
type NpsOut = z.output<typeof npsUpdateSchema>;

function NpsUpdateForm({
  id,
  row,
  onClose,
  onSaved,
}: {
  id: number;
  row: UpdateValueRow;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const { control, handleSubmit } = useForm<NpsIn, unknown, NpsOut>({
    resolver: zodResolver(npsUpdateSchema),
    defaultValues: npsDefaults(row),
  });
  const { saving, save } = useUpdateValue("nps", id, onClose, onSaved);
  const onSubmit = handleSubmit((v) => save(npsBody(v.units, v.contributed)));
  return (
    <FormShell
      onSubmit={onSubmit}
      saving={saving}
      editing
      onCancel={onClose}
      submitLabel="Save"
    >
      <TextField
        control={control}
        name="units"
        label="Units"
        inputMode="decimal"
        decimals={4}
        hint={currentFigureText("nps", row)}
        required
      />
      <TextField
        control={control}
        name="contributed"
        label="Contributed"
        adornment="₹"
        inputMode="decimal"
        decimals={2}
        required
      />
    </FormShell>
  );
}
