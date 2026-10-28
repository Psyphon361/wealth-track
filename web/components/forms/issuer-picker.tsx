"use client";

import { useEffect, useState } from "react";
import { FD_ISSUER_CATEGORY_LABELS, type FdIssuer } from "@/lib/types";
import { apiGet } from "@/lib/api";
import { MasterPicker } from "./master-picker";

const LINK_BUTTON =
  "w-fit text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline";

export function issuerMain(s: FdIssuer): string {
  return s.short_name ?? s.name;
}

/** Full name, only when it adds information beyond the main line. */
function issuerFullName(s: FdIssuer): string | null {
  const main = issuerMain(s).trim().toLowerCase();
  const full = s.name.trim();
  return full.toLowerCase() === main ? null : full;
}

function issuerMeta(s: FdIssuer): string {
  const parts: string[] = [FD_ISSUER_CATEGORY_LABELS[s.category] ?? s.category];
  if (s.dicgc_insured === true) parts.push("DICGC insured");
  if (s.merged_into) parts.push(`Merged into ${s.merged_into.name}`);
  return parts.join(" · ");
}

/** Holds the selected issuer's master details; loads them in edit mode. */
export function useIssuerMeta(initialId: number | null) {
  const [meta, setMeta] = useState<FdIssuer | null>(null);

  useEffect(() => {
    if (initialId === null) return;
    let cancelled = false;
    apiGet<FdIssuer>(`/master/fd-issuer/${initialId}`)
      .then((s) => {
        if (!cancelled) setMeta(s);
      })
      .catch(() => {
        // 404 or network: keep showing the stored bank text.
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  return [meta, setMeta] as const;
}

export function IssuerPicker({
  id,
  hasValue,
  meta,
  bankText,
  onSelect,
  onBlur,
  invalid,
}: {
  id?: string;
  hasValue: boolean;
  /** Master details for the current value, if known. */
  meta: FdIssuer | null;
  /** Stored bank text, shown until master details are known. */
  bankText: string;
  onSelect: (issuer: FdIssuer) => void;
  onBlur?: () => void;
  invalid?: boolean;
}) {
  return (
    <MasterPicker<FdIssuer>
      id={id}
      hasValue={hasValue}
      summary={
        <>
          <div className="truncate text-sm font-medium">
            {meta ? issuerMain(meta) : bankText}
          </div>
          {meta ? (
            <div className="truncate text-[11px] text-muted-foreground">
              {issuerFullName(meta) ? `${issuerFullName(meta)} · ` : ""}
              {issuerMeta(meta)}
            </div>
          ) : null}
        </>
      }
      searchPath={(q) =>
        `/master/fd-issuer?q=${encodeURIComponent(q)}&limit=20`
      }
      itemKey={(s) => s.id}
      itemLabel={(s) => s.name}
      renderItem={(s) => (
        <>
          <span className="truncate text-sm">
            {issuerMain(s)}
            {issuerFullName(s) ? (
              <span className="ml-1.5 text-[11px] text-muted-foreground">
                {issuerFullName(s)}
              </span>
            ) : null}
          </span>
          <span className="truncate text-[11px] text-muted-foreground">
            {issuerMeta(s)}
          </span>
        </>
      )}
      placeholder="Search banks and issuers…"
      emptyLabel="No matching banks or issuers"
      invalid={invalid}
      onBlur={onBlur}
      onSelect={onSelect}
    />
  );
}

export function IssuerModeToggle({
  mode,
  onChange,
}: {
  mode: "picker" | "manual";
  onChange: (next: "picker" | "manual") => void;
}) {
  return (
    <button
      type="button"
      className={LINK_BUTTON}
      onClick={() => onChange(mode === "picker" ? "manual" : "picker")}
    >
      {mode === "picker"
        ? "Not listed? Enter manually"
        : "Search the bank list instead"}
    </button>
  );
}
