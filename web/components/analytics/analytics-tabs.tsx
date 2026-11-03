"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/analytics", label: "Overview" },
  { href: "/analytics/performance", label: "Performance" },
];

/** Pill bar linking the analytics sub-pages. */
export function AnalyticsTabs() {
  const pathname = usePathname();

  const pill =
    "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[13.5px] whitespace-nowrap outline-none transition-colors focus-visible:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50";

  return (
    <nav aria-label="Analytics sections" className="min-w-0">
      <ul className="no-scrollbar flex items-center gap-1 overflow-x-auto p-1">
        {TABS.map((tab) => {
          const isActive =
            tab.href === "/analytics"
              ? pathname === "/analytics"
              : pathname === tab.href || pathname.startsWith(`${tab.href}/`);
          return (
            <li key={tab.href} className="shrink-0">
              <Link
                href={tab.href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  pill,
                  isActive
                    ? "border-border bg-muted font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
