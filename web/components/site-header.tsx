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
import { useBreadcrumbLabelValue } from "@/components/breadcrumb-label";
import { Skeleton } from "@/components/ui/skeleton";
import { UserMenu } from "@/components/user-menu";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { ASSET_SLUGS, getAssetEntry } from "@/lib/asset-catalog";
import { ASSET_TYPE_LABELS, type AssetType } from "@/lib/types";

type Crumb = { label: string; href?: string; pending?: boolean };

function getCrumbs(pathname: string, detailLabel: string | null): Crumb[] {
  if (pathname === "/") return [{ label: "Dashboard" }];
  if (pathname === "/portfolio") return [{ label: "Portfolio" }];
  if (pathname.startsWith("/portfolio/")) {
    const [slug, id] = pathname.slice("/portfolio/".length).split("/");
    if (id && ASSET_SLUGS.includes(slug as AssetType)) {
      return [
        { label: "Portfolio", href: "/portfolio" },
        { label: ASSET_TYPE_LABELS[slug as AssetType], href: `/portfolio/${slug}` },
        { label: detailLabel ?? "", pending: detailLabel === null },
      ];
    }
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
  const detailLabel = useBreadcrumbLabelValue();
  const crumbs = getCrumbs(pathname, detailLabel);
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
                <BreadcrumbItem className={last ? "min-w-0" : "shrink-0 whitespace-nowrap"}>
                  {last || !crumb.href ? (
                    crumb.pending ? (
                      <Skeleton className="h-4 w-24" />
                    ) : (
                      <BreadcrumbPage
                        className="block min-w-0 max-w-[40vw] truncate"
                        title={crumb.label}
                      >
                        {crumb.label}
                      </BreadcrumbPage>
                    )
                  ) : (
                    <BreadcrumbLink href={crumb.href} className="whitespace-nowrap">
                      {crumb.label}
                    </BreadcrumbLink>
                  )}
                </BreadcrumbItem>
              </Fragment>
            );
          })}
        </BreadcrumbList>
      </Breadcrumb>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <AddMenu />
        <UserMenu />
      </div>
    </header>
  );
}
