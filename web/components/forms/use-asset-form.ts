"use client";

import { useState } from "react";
import { notify } from "@/lib/notify";
import { ApiError, apiPost, apiPut, type ApiMessage } from "@/lib/api";
import type { AssetType, RecordFields } from "@/lib/types";

export type FieldIssue = { field: string; message: string };

/** Extract per-field messages from an API 422 `detail` array. */
function fieldIssues(err: unknown): FieldIssue[] {
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

  async function save(payload: unknown): Promise<void> {
    setSaving(true);
    try {
      const saved = record
        ? await apiPut<R>(`/assets/${type}/${record.id}`, payload)
        : await apiPost<R>(`/assets/${type}`, payload);
      notify.success(saved as Partial<ApiMessage>);
      onSaved?.(saved);
    } catch (e) {
      notify.error(e);
      const issues = fieldIssues(e);
      if (issues.length) onFieldIssues?.(issues);
    } finally {
      setSaving(false);
    }
  }

  return { saving, save };
}
