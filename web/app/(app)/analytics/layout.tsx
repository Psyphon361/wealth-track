import { Suspense } from "react";
import { AnalyticsTabs } from "@/components/analytics/analytics-tabs";

export default function AnalyticsLayout({
  children,
}: LayoutProps<"/analytics">) {
  return (
    <div className="-mt-4 min-w-0 space-y-4">
      <Suspense fallback={<div className="h-9" />}>
        <AnalyticsTabs />
      </Suspense>
      {children}
    </div>
  );
}
