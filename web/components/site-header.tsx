"use client";

import { usePathname } from "next/navigation";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/portfolio": "Portfolio",
  "/add": "Add asset",
};

export function SiteHeader() {
  const pathname = usePathname();
  const title = TITLES[pathname] ?? "Wealth Tracker";
  return (
    <header className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="data-vertical:h-4 data-vertical:self-center" />
      <h1 className="text-sm font-medium">{title}</h1>
    </header>
  );
}
