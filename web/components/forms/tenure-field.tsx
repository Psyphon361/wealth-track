"use client";

import { useEffect, useState } from "react";
import {
  useFormState,
  useWatch,
  type Control,
  type FieldValues,
  type UseFormSetValue,
  type UseFormTrigger,
} from "react-hook-form";
import { FieldError } from "@/components/ui/field";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { formatDate } from "@/lib/format";
import { DateField } from "./fields";
import { addPeriodISO, diffPeriodISO, isValidISODate } from "./schema";
import { TenurePicker } from "./tenure-picker";

/** Field names the tenure block reads and writes (all string values). */
type TenureValues = {
  start_date: string;
  tenure_years: string;
  tenure_months: string;
  tenure_days: string;
  maturity_date: string;
};

type TenureMode = "duration" | "maturity";

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

/**
 * Tenure input with a "Duration / Maturity date" toggle. Maturity mode takes a
 * form-only `maturity_date` and derives tenure_years/months/days from it.
 * The form must strip `maturity_date` from its payload.
 */
export function TenureField<T extends FieldValues & TenureValues, TOut>({
  control,
  setValue,
  trigger,
}: {
  control: Control<T, unknown, TOut>;
  setValue: UseFormSetValue<T>;
  trigger: UseFormTrigger<T>;
}) {
  const c = control as unknown as Control<TenureValues>;
  const set = setValue as unknown as UseFormSetValue<TenureValues>;
  const trig = trigger as unknown as UseFormTrigger<TenureValues>;

  const [tenureMode, setTenureMode] = useState<TenureMode>("duration");
  const startDate = useWatch({ control: c, name: "start_date" });
  const maturityDate = useWatch({ control: c, name: "maturity_date" });
  const tYears = useWatch({ control: c, name: "tenure_years" });
  const tMonths = useWatch({ control: c, name: "tenure_months" });
  const tDays = useWatch({ control: c, name: "tenure_days" });
  const { errors } = useFormState({ control: c });
  const tenureError = [
    errors.tenure_years,
    errors.tenure_months,
    errors.tenure_days,
  ].find((e) => typeof e?.message === "string");
  const years = Number(tYears) || 0;
  const months = Number(tMonths) || 0;
  const days = Number(tDays) || 0;
  const tenureTotal = years + months + days;
  const startOk = isValidISODate(startDate);

  function switchTenureMode(next: TenureMode) {
    if (next === tenureMode) return;
    if (next === "maturity") {
      set(
        "maturity_date",
        startOk && tenureTotal > 0
          ? addPeriodISO(startDate, years, months, days)
          : "",
      );
    }
    setTenureMode(next);
  }

  useEffect(() => {
    if (tenureMode !== "maturity") return;
    if (!isValidISODate(maturityDate)) return;
    const d = diffPeriodISO(startDate, maturityDate);
    const opts = { shouldDirty: true };
    set("tenure_years", String(d.years), opts);
    set("tenure_months", String(d.months), opts);
    set("tenure_days", String(d.days), opts);
    void trig(["tenure_years", "tenure_months", "tenure_days"]);
  }, [tenureMode, maturityDate, startDate, set, trig]);

  const hasTenureError = !!tenureError;
  useEffect(() => {
    if (hasTenureError) {
      void trig(["tenure_years", "tenure_months", "tenure_days"]);
    }
  }, [tYears, tMonths, tDays, hasTenureError, trig]);

  const tenureText = [
    years ? plural(years, "year") : "",
    months ? plural(months, "month") : "",
    days ? plural(days, "day") : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="flex flex-col gap-1.5 sm:col-span-2">
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">Tenure</span>
        <ToggleGroup
          value={[tenureMode]}
          onValueChange={(v) => {
            if (v[0]) switchTenureMode(v[0] as TenureMode);
          }}
          variant="outline"
          size="sm"
          spacing={0}
          className="h-6"
        >
          <ToggleGroupItem value="duration" className="h-6 px-2 text-xs">
            Duration
          </ToggleGroupItem>
          <ToggleGroupItem value="maturity" className="h-6 px-2 text-xs">
            Maturity date
          </ToggleGroupItem>
        </ToggleGroup>
      </div>
      {tenureMode === "duration" ? (
        <>
          <TenurePicker
            hideLabel
            control={c}
            names={{
              years: "tenure_years",
              months: "tenure_months",
              days: "tenure_days",
            }}
          />
          {startOk && tenureTotal > 0 ? (
            <p className="text-xs text-muted-foreground">
              Matures on{" "}
              <span className="num">
                {formatDate(addPeriodISO(startDate, years, months, days))}
              </span>
            </p>
          ) : null}
        </>
      ) : (
        <>
          <DateField
            control={c}
            name="maturity_date"
            label="Maturity date"
            required
          />
          {tenureTotal > 0 ? (
            <p className="text-xs text-muted-foreground">
              Tenure: {tenureText}
            </p>
          ) : null}
          <FieldError
            errors={tenureError ? [{ message: String(tenureError.message) }] : []}
            className="text-xs text-destructive"
          />
        </>
      )}
    </div>
  );
}
