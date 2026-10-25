"use client";

import { Fragment } from "react";
import { usePathname } from "next/navigation";
import { AddMenu } from "@/components/add-menu";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ASSET_SLUGS, getAssetEntry } from "@/lib/asset-catalog";
import { ASSET_TYPE_LABELS, type AssetType } from "@/lib/types";

type Crumb = { label: string; href?: string };

function getCrumbs(pathname: string): Crumb[] {
  if (pathname === "/") return [{ label: "Dashboard" }];
  if (pathname === "/portfolio") return [{ label: "Portfolio" }];
  if (pathname.startsWith("/portfolio/")) {
    const slug = pathname.slice("/portfolio/".length).split("/")[0];
    return ASSET_SLUGS.includes(slug as AssetType)
      ? [
          { label: "Portfolio", href: "/portfolio" },
          { label: ASSET_TYPE_LABELS[slug as AssetType] },
        ]
      : [{ label: "Portfolio", href: "/portfolio" }];
  }
  if (pathname === "/add") return [{ label: "Add asset" }];
  if (pathname.startsWith("/add/")) {
    const slug = pathname.slice("/add/".length).split("/")[0];
    const entry = getAssetEntry(slug);
    return entry
      ? [{ label: "Add asset", href: "/add" }, { label: entry.title }]
      : [{ label: "Add asset", href: "/add" }];
  }
  return [{ label: "Wealth Tracker" }];
}

export function SiteHeader() {
  const pathname = usePathname();
  const crumbs = getCrumbs(pathname);
  return (
    <header className="sticky top-0 z-10 flex h-12 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur md:rounded-t-xl">
      <SidebarTrigger className="-ml-1" />
      <Separator orientation="vertical" className="data-vertical:h-4 data-vertical:self-center" />
      <Breadcrumb className="min-w-0">
        <BreadcrumbList className="flex-nowrap">
          {crumbs.map((crumb, i) => {
            const last = i === crumbs.length - 1;
            return (
              <Fragment key={crumb.label}>
                {i > 0 ? <BreadcrumbSeparator /> : null}
                <BreadcrumbItem>
                  {last || !crumb.href ? (
                    <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                  ) : (
                    <BreadcrumbLink href={crumb.href}>{crumb.label}</BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </Fragment>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto shrink-0">
        <AddMenu />
      </div>
    </header>
  );
}
