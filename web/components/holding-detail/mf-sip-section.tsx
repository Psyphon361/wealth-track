"use client";

import Link from "next/link";
import { Card } from "@/components/ui/card";
import { Button, buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SipActions } from "@/components/sips/sip-actions";
import { SipBadge, SipProgressLine } from "@/components/sips/sip-badge";
import { useSips } from "@/components/sips/use-sips";
import { ADD_SIP_HREF, sinceText } from "@/lib/sip";
import { LABEL } from "./sections";

/** The SIPs feeding this holding, with the same actions as the SIPs list. */
export function MfSipSection({ id }: { id: number }) {
  const { sips, error, reload, retry } = useSips(id);

  return (
    <Card size="sm" className="gap-3 px-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className={LABEL}>SIP</h3>
        {sips && sips.length === 0 ? (
          <Link
            href={ADD_SIP_HREF}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Start a SIP
          </Link>
        ) : null}
      </div>
      {error && !sips ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-[13.5px] font-medium text-destructive">
              {error.message}
            </p>
            {error.description ? (
              <p className="text-[13.2px] text-muted-foreground">
                {error.description}
              </p>
            ) : null}
          </div>
          <Button variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </div>
      ) : !sips ? (
        <div className="space-y-2" aria-busy="true" aria-label="Loading SIP">
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-3.5 w-48" />
        </div>
      ) : sips.length === 0 ? (
        <p className="text-[13.2px] text-muted-foreground">
          No SIP is feeding this holding.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border/50">
          {sips.map((s) => (
            <li
              key={s.id}
              className="flex items-start justify-between gap-3 py-2 first:pt-0 last:pb-0"
            >
              <div className="min-w-0 space-y-0.5">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="num text-[13.5px] font-medium">
                    {sinceText(s)}
                  </p>
                  <SipBadge status={s.status} />
                </div>
                <p className="text-xs text-muted-foreground">{s.platform}</p>
                <SipProgressLine sip={s} />
              </div>
              <SipActions sip={s} onChanged={reload} showLabel />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
