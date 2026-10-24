"use client";

import { useState } from "react";
import { toast } from "sonner";
import { apiPost, apiPut } from "@/lib/api";
import type { AssetType, RecordFields } from "@/lib/types";

export function useAssetSave<R extends RecordFields>(
  type: AssetType,
  record: R | undefined,
  onSaved?: (record: R) => void,
) {
  const [saving, setSaving] = useState(false);

  async function save(payload: unknown): Promise<void> {
    setSaving(true);
    try {
      const saved = record
        ? await apiPut<R>(`/assets/${type}/${record.id}`, payload)
        : await apiPost<R>(`/assets/${type}`, payload);
      toast.success(record ? "Asset updated" : "Asset added");
      onSaved?.(saved);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  }

  return { saving, save };
}
