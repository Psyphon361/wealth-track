"use client";

import { formatDate } from "@/lib/format";
import type { MfOption, MfPlan, MfScheme } from "@/lib/types";
import { MasterPicker } from "./master-picker";

export type SchemeValue = { scheme_code: number; name: string } | null;

const PLAN_LABELS: Record<MfPlan, string> = {
  direct: "Direct",
  regular: "Regular",
};

const OPTION_LABELS: Record<MfOption, string> = {
  growth: "Growth",
  idcw: "IDCW",
  bonus: "Bonus",
  other: "Other",
};

const FREQUENCY_LABELS: Record<string, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
  quarterly: "Quarterly",
  half_yearly: "Half-yearly",
  annual: "Annual",
};

type SchemeMeta = Pick<
  MfScheme,
  "amc" | "plan" | "option" | "idcw_frequency"
>;

function metaLine(s: SchemeMeta): string {
  const parts: string[] = [s.amc];
  if (s.plan) parts.push(PLAN_LABELS[s.plan] ?? s.plan);
  if (s.option) {
    let opt = OPTION_LABELS[s.option] ?? s.option;
    if (s.idcw_frequency) {
      opt += ` · ${FREQUENCY_LABELS[s.idcw_frequency] ?? s.idcw_frequency}`;
    }
    parts.push(opt);
  }
  return parts.filter(Boolean).join(" · ");
}

const nav4 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function SchemePicker({
  id,
  value,
  scheme,
  onSelect,
  onBlur,
  invalid,
}: {
  id?: string;
  value: SchemeValue;
  /** Master details for the current value (for the summary line), if known. */
  scheme?: SchemeMeta | null;
  onSelect: (scheme: MfScheme) => void;
  onBlur?: () => void;
  invalid?: boolean;
}) {
  return (
    <MasterPicker<MfScheme>
      id={id}
      hasValue={value !== null}
      summary={
        value ? (
          <>
            <div className="truncate text-sm font-medium">{value.name}</div>
            {scheme ? (
              <div className="truncate text-[11px] text-muted-foreground">
                {metaLine(scheme)}
              </div>
            ) : null}
          </>
        ) : null
      }
      searchPath={(q) => `/master/mf?q=${encodeURIComponent(q)}&limit=20`}
      itemKey={(s) => s.scheme_code}
      itemLabel={(s) => s.name}
      renderItem={(s) => (
        <>
          <span className="truncate text-sm">{s.name}</span>
          <span className="flex items-baseline gap-2 text-[11px] text-muted-foreground">
            <span className="min-w-0 flex-1 truncate">{metaLine(s)}</span>
            {s.nav !== null && s.nav_date ? (
              <span className="num shrink-0">
                ₹{nav4.format(s.nav)} · {formatDate(s.nav_date)}
              </span>
            ) : null}
          </span>
        </>
      )}
      placeholder="Search mutual fund schemes…"
      emptyLabel="No matching schemes"
      onSelect={onSelect}
      onBlur={onBlur}
      invalid={invalid}
    />
  );
}
