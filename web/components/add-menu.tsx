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

/**
 * Modal overlays: dialogs, alert dialogs and sheets (all base-ui dialog popups, told apart from
 * non-modal popovers, which also have role="dialog", by their data-slot) and open menus.
 */
const MODAL_SELECTOR =
  '[data-slot="dialog-content"], [data-slot="alert-dialog-content"], [data-slot="sheet-content"], [role="menu"]';

/**
 * A modal overlay is on screen. Elements that are not displayed (a hidden Activity route, a
 * kept-mounted popup) and popups mid-close never count. `except` skips matching elements.
 */
export function modalOverlayVisible(except?: string): boolean {
  for (const el of document.querySelectorAll(MODAL_SELECTOR)) {
    if (except && el.matches(except)) continue;
    if (el.matches("[data-closed], [data-ending-style]")) continue;
    if (el.getClientRects().length > 0) return true;
  }
  return false;
}

export function shouldIgnoreKey(e: KeyboardEvent): boolean {
  if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat) return true;
  const el = e.target as HTMLElement | null;
  if (el) {
    const tag = el.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
    if (el.isContentEditable) return true;
    if (
      el.closest(
        '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]',
      )
    )
      return true;
  }
  return modalOverlayVisible();
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
        {ASSET_GROUPS.map((group) => (
          <Fragment key={group}>
            <DropdownMenuGroup>
              <DropdownMenuLabel>{group}</DropdownMenuLabel>
              {ASSET_CATALOG.filter((a) => a.group === group).map(renderItem)}
            </DropdownMenuGroup>
          </Fragment>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/add" />}>
          <LayoutGrid />
          All asset types
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
