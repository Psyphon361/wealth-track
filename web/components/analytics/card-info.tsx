"use client";

import { Info } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

// Info icon after a card label. Opens on hover, focus-click and tap (popover, not tooltip,
// because base-ui tooltips don't open on touch).
export function CardInfo({ children }: { children: React.ReactNode }) {
  return (
    <Popover>
      <PopoverTrigger
        openOnHover
        delay={100}
        aria-label="About this section"
        className="inline-flex shrink-0 items-center rounded-full text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Info className="size-3.5" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent
        side="top"
        className="w-auto max-w-[16rem] gap-0 p-2 text-[13.2px] leading-snug"
      >
        {children}
      </PopoverContent>
    </Popover>
  );
}
