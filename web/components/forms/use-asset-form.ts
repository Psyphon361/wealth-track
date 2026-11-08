"use client";

import { useState } from "react";
import { notify } from "@/lib/notify";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { markHoldingsChanged } from "@/lib/holdings-cache";
import { ApiError, apiPost, apiPut, type ApiMessage } from "@/lib/api";
import { confirmDuplicatePath, duplicateHref } from "@/lib/duplicates";
import type { AssetType, RecordFields } from "@/lib/types";
import { useDuplicateWarning } from "./duplicate-dialog";

export type FieldIssue = { field: string; message: string };

/** Extract per-field messages from an API 422 `detail` array. */
export function fieldIssues(err: unknown): FieldIssue[] {
  if (!(err instanceof ApiError) || err.status !== 422) return [];
  if (!Array.isArray(err.detail)) return [];
  const out: FieldIssue[] = [];
  for (const d of err.detail as unknown[]) {
    if (!d || typeof d !== "object") continue;
    const { loc, msg } = d as { loc?: unknown; msg?: unknown };
    if (!Array.isArray(loc) || typeof msg !== "string") continue;
    const field = loc.filter((p) => typeof p === "string" && p !== "body").pop();
    if (typeof field === "string") out.push({ field, message: msg });
  }
  return out;
}

export function useAssetSave<R extends RecordFields>(
  type: AssetType,
  record: R | undefined,
  onSaved?: (record: R) => void,
  onFieldIssues?: (issues: FieldIssue[]) => void,
) {
  const [saving, setSaving] = useState(false);
  const warning = useDuplicateWarning((m) => duplicateHref(type, m.id));

  function done(saved: R, payload?: unknown) {
    invalidateNetWorth();
    const paid =
      !!payload && typeof payload === "object" && "paid_from" in payload && !!payload.paid_from;
    markHoldingsChanged(type, paid);
    notify.success(saved as Partial<ApiMessage>);
    onSaved?.(saved);
  }

  function failed(e: unknown) {
    notify.error(e);
    const issues = fieldIssues(e);
    if (issues.length) onFieldIssues?.(issues);
  }

  async function save(payload: unknown): Promise<void> {
    setSaving(true);
    try {
      if (record) {
        done(await apiPut<R>(`/assets/${type}/${record.id}`, payload), payload);
      } else {
        done(await apiPost<R>(`/assets/${type}`, payload), payload);
      }
    } catch (e) {
      // Create only: a 409 duplicate warning opens the dialog instead of a toast.
      const confirmed = async () => {
        try {
          done(
            await apiPost<R>(
              confirmDuplicatePath(`/assets/${type}`),
              payload,
            ),
            payload,
          );
        } catch (err) {
          failed(err);
        }
      };
      if (record || !warning.intercept(e, confirmed)) failed(e);
    } finally {
      setSaving(false);
    }
  }

  return {
    saving: saving || warning.busy,
    save,
    /** Pass to FormShell's `duplicate` prop. */
    duplicate: warning.props,
  };
}
