"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { AssetForm } from "@/components/forms/asset-form";
import { Field, FieldLabel } from "@/components/ui/field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ASSET_TYPE_LABELS, type AssetType } from "@/lib/types";

const OPTIONS = (Object.keys(ASSET_TYPE_LABELS) as AssetType[]).map((value) => ({
  value,
  label: ASSET_TYPE_LABELS[value],
}));

export function AddAssetFlow({ initialType }: { initialType: AssetType }) {
  const router = useRouter();
  const [type, setType] = useState<AssetType>(initialType);
  const onSaved = () => router.push("/portfolio");

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">Add asset</h1>
      <Field>
        <FieldLabel htmlFor="asset-type">Asset type</FieldLabel>
        <Select
          items={OPTIONS}
          value={type}
          onValueChange={(v) => {
            if (v) setType(v as AssetType);
          }}
        >
          <SelectTrigger id="asset-type" className="w-full sm:w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {OPTIONS.map((o) => (
              <SelectItem key={o.value} value={o.value}>
                {o.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {type === "fd" && <AssetForm type="fd" onSaved={onSaved} />}
      {type === "rd" && <AssetForm type="rd" onSaved={onSaved} />}
      {type === "stock" && <AssetForm type="stock" onSaved={onSaved} />}
      {type === "bond" && <AssetForm type="bond" onSaved={onSaved} />}
      {type === "mf" && <AssetForm type="mf" onSaved={onSaved} />}
    </div>
  );
}
