"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Landmark,
  LineChart,
  PieChart,
  Repeat,
  ScrollText,
  type LucideIcon,
} from "lucide-react";
import { AssetForm } from "@/components/forms/asset-form";
import { Card, CardContent } from "@/components/ui/card";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { AssetType } from "@/lib/types";

const OPTIONS: { value: AssetType; label: string; icon: LucideIcon }[] = [
  { value: "fd", label: "FD", icon: Landmark },
  { value: "rd", label: "RD", icon: Repeat },
  { value: "stock", label: "Stock", icon: LineChart },
  { value: "bond", label: "Bond", icon: ScrollText },
  { value: "mf", label: "MF", icon: PieChart },
];

export function AddAssetFlow({ initialType }: { initialType: AssetType }) {
  const router = useRouter();
  const [type, setType] = useState<AssetType>(initialType);
  const onSaved = () => router.push("/portfolio");
  const onCancel = () => router.back();

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <ToggleGroup
        aria-label="Asset type"
        variant="outline"
        size="sm"
        spacing={1}
        value={[type]}
        onValueChange={(v) => {
          const next = OPTIONS.find((o) => o.value === v[0]);
          if (next) setType(next.value);
        }}
        className="flex-wrap"
      >
        {OPTIONS.map((o) => (
          <ToggleGroupItem key={o.value} value={o.value} aria-label={o.label}>
            <o.icon />
            {o.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <Card size="sm">
        <CardContent>
          {type === "fd" && (
            <AssetForm type="fd" onSaved={onSaved} onCancel={onCancel} />
          )}
          {type === "rd" && (
            <AssetForm type="rd" onSaved={onSaved} onCancel={onCancel} />
          )}
          {type === "stock" && (
            <AssetForm type="stock" onSaved={onSaved} onCancel={onCancel} />
          )}
          {type === "bond" && (
            <AssetForm type="bond" onSaved={onSaved} onCancel={onCancel} />
          )}
          {type === "mf" && (
            <AssetForm type="mf" onSaved={onSaved} onCancel={onCancel} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
