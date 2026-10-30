"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { AssetForm } from "@/components/forms/asset-form";
import { CasImport } from "@/components/forms/cas-import/cas-import";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { getAssetEntry } from "@/lib/asset-catalog";
import type { AssetType } from "@/lib/types";

export function AddFormPage({ type }: { type: AssetType }) {
  const router = useRouter();
  // The route stays mounted after leaving it (cacheComponents), so bump the
  // key to remount the form blank for the next visit.
  const [formKey, setFormKey] = useState(0);
  const [mfTab, setMfTab] = useState<"manual" | "cas">("manual");
  const entry = getAssetEntry(type);
  if (!entry) return null;
  const onSaved = () => {
    setFormKey((k) => k + 1);
    router.push(`/portfolio/${type}`);
  };
  const onCancel = () => {
    setFormKey((k) => k + 1);
    router.push("/add");
  };

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-4">
      <div className="flex items-center gap-3">
        <AssetTypeIcon icon={entry.icon} />
        <h2 className="text-base font-medium">{entry.title}</h2>
      </div>
      {type === "mf" && (
        <ToggleGroup
          value={[mfTab]}
          onValueChange={(v) => {
            if (v[0]) setMfTab(v[0] as "manual" | "cas");
          }}
          variant="outline"
          size="sm"
          spacing={0}
          className="h-6 self-start"
        >
          <ToggleGroupItem value="manual" className="h-6 px-2 text-xs">
            Manual entry
          </ToggleGroupItem>
          <ToggleGroupItem value="cas" className="h-6 px-2 text-xs">
            Import CAS
          </ToggleGroupItem>
        </ToggleGroup>
      )}
      <Card className="min-w-0 px-5 py-4 md:px-8 md:py-5">
        <CardContent className="min-w-0 px-0">
          {type === "mf" && mfTab === "cas" && (
            <CasImport key={`cas-${formKey}`} onImported={onSaved} />
          )}
          {type === "fd" && (
            <AssetForm
              key={formKey}
              type="fd"
              onSaved={onSaved}
              onCancel={onCancel}
            />
          )}
          {type === "rd" && (
            <AssetForm
              key={formKey}
              type="rd"
              onSaved={onSaved}
              onCancel={onCancel}
            />
          )}
          {type === "stock" && (
            <AssetForm
              key={formKey}
              type="stock"
              onSaved={onSaved}
              onCancel={onCancel}
            />
          )}
          {type === "bond" && (
            <AssetForm
              key={formKey}
              type="bond"
              onSaved={onSaved}
              onCancel={onCancel}
            />
          )}
          {type === "mf" && mfTab === "manual" && (
            <AssetForm
              key={formKey}
              type="mf"
              onSaved={onSaved}
              onCancel={onCancel}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
