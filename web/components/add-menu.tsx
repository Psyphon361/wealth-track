"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGrid, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ASSET_CATALOG, ASSET_GROUPS } from "@/lib/asset-catalog";

function shouldIgnoreKey(e: KeyboardEvent): boolean {
  if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat) return true;
  const el = e.target as HTMLElement | null;
  if (el) {
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (el.isContentEditable) return true;
    if (el.closest('[role="dialog"], [role="alertdialog"], [role="menu"]')) return true;
  }
  return !!document.querySelector(
    '[role="dialog"], [role="alertdialog"], [role="menu"]',
  );
}

export function AddMenu() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const hidden = pathname === "/add" || pathname.startsWith("/add/");

  useEffect(() => {
    if (hidden) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key.toLowerCase() !== "n" || shouldIgnoreKey(e)) return;
      e.preventDefault();
      setOpen(true);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [hidden]);

  if (hidden) return null;

  const current = pathname.startsWith("/portfolio/")
    ? pathname.slice("/portfolio/".length).split("/")[0]
    : null;
  const ordered = [...ASSET_CATALOG].sort(
    (a, b) => Number(b.type === current) - Number(a.type === current),
  );
  const contextual = ordered.some((a, i) => i === 0 && a.type === current);

  function renderItem(entry: (typeof ASSET_CATALOG)[number]) {
    return (
      <DropdownMenuItem
        key={entry.type}
        render={<Link href={`/add/${entry.type}`} />}
      >
        <entry.icon />
        {entry.title}
      </DropdownMenuItem>
    );
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger
          render={
            <DropdownMenuTrigger
              render={<Button aria-label="Add asset" />}
            />
          }
        >
          <Plus aria-hidden />
          <span className="hidden sm:inline">Add asset</span>
        </TooltipTrigger>
        <TooltipContent side="bottom">Add asset (N)</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-52">
        {contextual ? (
          <DropdownMenuGroup>{ordered.map(renderItem)}</DropdownMenuGroup>
        ) : (
          ASSET_GROUPS.map((group) => (
            <Fragment key={group}>
              <DropdownMenuGroup>
                <DropdownMenuLabel>{group}</DropdownMenuLabel>
                {ordered.filter((a) => a.group === group).map(renderItem)}
              </DropdownMenuGroup>
            </Fragment>
          ))
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/add" />}>
          <LayoutGrid />
          All asset types
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
