"use client";

import { useState } from "react";
import { notify } from "@/lib/notify";
import { apiPost, apiPut, type ApiMessage } from "@/lib/api";
import type { AssetType, RecordFields } from "@/lib/types";

export function useAssetSave<R extends RecordFields>(
  type: AssetType,
  record: R | undefined,
  onSaved?: (record: R) => void,
) {
  const [saving, setSaving] = useState(false);

  async function save(payload: unknown): Promise<void> {
    setSaving(true);
    const toastId = notify.saving();
    try {
      const saved = record
        ? await apiPut<R>(`/assets/${type}/${record.id}`, payload)
        : await apiPost<R>(`/assets/${type}`, payload);
      notify.success(saved as Partial<ApiMessage>, toastId);
      onSaved?.(saved);
    } catch (e) {
      notify.error(e, toastId);
    } finally {
      setSaving(false);
    }
  }

  return { saving, save };
}
