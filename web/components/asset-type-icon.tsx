import type { LucideIcon } from "lucide-react";

/** Tinted rounded square holding an asset-type icon (page headers). */
export function AssetTypeIcon({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
      <Icon className="size-5" />
    </div>
  );
}
