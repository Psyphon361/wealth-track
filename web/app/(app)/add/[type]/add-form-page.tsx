"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { AssetForm } from "@/components/forms/asset-form";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { getAssetEntry } from "@/lib/asset-catalog";
import type { AssetType } from "@/lib/types";

export function AddFormPage({ type }: { type: AssetType }) {
  const router = useRouter();
  const entry = getAssetEntry(type);
  if (!entry) return null;
  const onSaved = () => router.push("/portfolio");
  const onCancel = () => router.push("/add");

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <div className="flex flex-col items-start gap-3">
        <Link
          href="/add"
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowLeft />
          All assets
        </Link>
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <entry.icon className="size-5" />
          </div>
          <h2 className="text-base font-medium">{entry.title}</h2>
        </div>
      </div>
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
