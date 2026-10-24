import { AssetTabs } from "@/components/portfolio/asset-tabs";

export default function PortfolioLayout({
  children,
}: LayoutProps<"/portfolio">) {
  return (
    <div className="min-w-0 space-y-4">
      <AssetTabs />
      {children}
    </div>
  );
}
