"use client";

import { formatDate } from "@/lib/format";
import {
  NPS_ASSET_CLASS_LABELS,
  NPS_TIER_LABELS,
  type NpsScheme,
} from "@/lib/types";
import { MasterPicker } from "./master-picker";

export type NpsSchemeValue = { scheme_id: string; name: string } | null;

type SchemeMeta = Pick<NpsScheme, "pfm_name" | "tier" | "asset_class">;

function metaLine(s: SchemeMeta): string {
  return [
    s.pfm_name,
    s.tier ? NPS_TIER_LABELS[s.tier] : null,
    NPS_ASSET_CLASS_LABELS[s.asset_class],
  ]
    .filter(Boolean)
    .join(" · ");
}

const nav4 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

export function NpsSchemePicker({
  id,
  value,
  scheme,
  onSelect,
  onBlur,
  invalid,
}: {
  id?: string;
  value: NpsSchemeValue;
  /** Master details for the current value (for the summary line), if known. */
  scheme?: SchemeMeta | null;
  onSelect: (scheme: NpsScheme) => void;
  onBlur?: () => void;
  invalid?: boolean;
}) {
  return (
    <MasterPicker<NpsScheme>
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
      searchPath={(q) => `/master/nps?q=${encodeURIComponent(q)}&limit=20`}
      itemKey={(s) => s.scheme_id}
      itemLabel={(s) => s.scheme_name}
      renderItem={(s) => (
        <>
          <span className="truncate text-sm">{s.scheme_name}</span>
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
      placeholder="Search NPS schemes…"
      emptyLabel="No matching schemes"
      onSelect={onSelect}
      onBlur={onBlur}
      invalid={invalid}
    />
  );
}
