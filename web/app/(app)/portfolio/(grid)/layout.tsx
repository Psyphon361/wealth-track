import { Suspense } from "react";
import { AssetTabs } from "@/components/portfolio/asset-tabs";

export default function PortfolioLayout({
  children,
}: LayoutProps<"/portfolio">) {
  return (
    <div className="min-w-0 space-y-4">
      <Suspense fallback={<div className="h-9 border-b" />}>
        <AssetTabs />
      </Suspense>
      {children}
    </div>
  );
}
