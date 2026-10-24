"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { apiGet, toApiMessage, type ApiMessage } from "@/lib/api";
import type { AssetType, DashboardResponse } from "@/lib/types";
import { TableSkeleton } from "./grid/data-table";

const ORDER: AssetType[] = ["fd", "rd", "stock", "bond", "mf"];

/** Sends /portfolio to the first asset type that has holdings. */
export function PortfolioRedirect() {
  const router = useRouter();
  const [error, setError] = useState<ApiMessage | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    apiGet<DashboardResponse>("/dashboard")
      .then((res) => {
        if (cancelled) return;
        const first = ORDER.find((t) =>
          res.by_type.some((r) => r.type === t && r.count > 0),
        );
        router.replace(`/portfolio/${first ?? "fd"}`);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(toApiMessage(err));
      });
    return () => {
      cancelled = true;
    };
  }, [attempt, router]);

  function retry() {
    setError(null);
    setAttempt((a) => a + 1);
  }

  if (error) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
        <div>
          <p className="text-sm font-medium text-destructive">
            {error.message}
          </p>
          {error.description ? (
            <p className="text-sm text-muted-foreground">
              {error.description}
            </p>
          ) : null}
        </div>
        <Button variant="outline" onClick={retry}>
          Retry
        </Button>
      </div>
    );
  }

  return <TableSkeleton />;
}
