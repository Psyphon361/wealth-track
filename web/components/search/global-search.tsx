"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Search } from "lucide-react";
import { shouldIgnoreKey } from "@/components/add-menu";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { SearchPanel } from "./search-panel";
import { preloadSearchIndex } from "./search-store";
import { useIsMac, useVisualViewport } from "./use-browser";

/** Another dialog, alert dialog, menu or select popup is open (not this palette). */
function otherOverlayOpen(): boolean {
  return (
    document.querySelector(
      '[role="dialog"]:not([data-search-palette]), [role="alertdialog"], [role="menu"], [role="listbox"]:not([cmdk-list])',
    ) !== null
  );
}

/**
 * Top-bar search: trigger buttons, the shortcuts, and the palette (desktop dialog or mobile
 * full-screen sheet around one shared panel). The panel mounts only while open, so its query,
 * expansion and selection reset on close.
 */
export function GlobalSearch() {
  const pathname = usePathname();
  const isMobile = useIsMobile();
  const isMac = useIsMac();
  const viewport = useVisualViewport();
  const [open, setOpen] = useState(false);

  /** Mirrors `open` so event handlers never read a stale value. */
  const openRef = useRef(false);
  /** The history entry we pushed on mobile is still in the stack. */
  const ownEntryRef = useRef(false);
  const openedAtRef = useRef("");
  const restoreRef = useRef<HTMLElement | null>(null);
  const desktopTriggerRef = useRef<HTMLButtonElement>(null);
  const mobileTriggerRef = useRef<HTMLButtonElement>(null);
  const bridgeRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const openSearch = useCallback(() => {
    if (openRef.current) return;
    openRef.current = true;
    const active = document.activeElement;
    restoreRef.current =
      active instanceof HTMLElement && active !== document.body && active !== bridgeRef.current
        ? active
        : null;
    openedAtRef.current = window.location.pathname;
    if (window.matchMedia("(max-width: 767px)").matches) {
      // So the phone's Back button closes the sheet instead of leaving the page.
      window.history.pushState({ wtSearch: true }, "");
      ownEntryRef.current = true;
    }
    setOpen(true);
  }, []);

  /** The user closed it (Esc, Cancel, outside click, shortcut): pop our history entry too. */
  const requestClose = useCallback(() => {
    if (!openRef.current) return;
    openRef.current = false;
    if (ownEntryRef.current) {
      ownEntryRef.current = false;
      window.history.back();
    }
    setOpen(false);
  }, []);

  /** Closed because a result was opened: the entry is already replaced, or the page changed. */
  const closeNow = useCallback(() => {
    if (!openRef.current) return;
    openRef.current = false;
    ownEntryRef.current = false;
    setOpen(false);
  }, []);

  useEffect(() => preloadSearchIndex(), []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        if (e.repeat) {
          e.preventDefault();
          return;
        }
        if (openRef.current) {
          e.preventDefault();
          requestClose();
        } else if (!otherOverlayOpen()) {
          e.preventDefault();
          openSearch();
        }
        return;
      }
      if (e.key === "/" && !shouldIgnoreKey(e)) {
        e.preventDefault();
        openSearch();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openSearch, requestClose]);

  // The phone's Back button (or a swipe) pops our entry: close without calling back() again.
  useEffect(() => {
    if (!open) return;
    function onPopState() {
      if (!ownEntryRef.current) return;
      ownEntryRef.current = false;
      openRef.current = false;
      setOpen(false);
    }
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [open]);

  // Any route change closes it.
  useEffect(() => {
    if (openRef.current && pathname !== openedAtRef.current) closeNow();
  }, [pathname, closeNow]);

  const finalFocus = useCallback((): HTMLElement | null => {
    const previous = restoreRef.current;
    if (previous?.isConnected) return previous;
    const desktop = desktopTriggerRef.current;
    return desktop && desktop.offsetParent !== null ? desktop : mobileTriggerRef.current;
  }, []);

  const initialFocus = useCallback(() => inputRef.current, []);

  function onMobileTap() {
    openSearch();
    // iOS only raises the keyboard for a focus() made inside the tap. Focus a hidden input now;
    // the panel moves focus to the real input once it has mounted.
    bridgeRef.current?.focus({ preventScroll: true });
  }

  const panel = (variant: "desktop" | "mobile") => (
    <SearchPanel
      variant={variant}
      inputRef={inputRef}
      isMac={isMac}
      keyboardOpen={viewport?.keyboardOpen ?? false}
      onClose={requestClose}
      onNavigated={closeNow}
    />
  );

  return (
    <>
      <input
        ref={bridgeRef}
        aria-hidden="true"
        tabIndex={-1}
        inputMode="search"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        className="pointer-events-none fixed top-0 left-0 size-px opacity-0 md:hidden"
        style={{ fontSize: 16 }}
      />
      <button
        ref={desktopTriggerRef}
        type="button"
        onClick={openSearch}
        aria-label="Search"
        aria-haspopup="dialog"
        aria-keyshortcuts="Meta+K Control+K"
        className="hidden h-9 items-center gap-2 rounded-lg border border-input bg-input/30 px-3 text-left text-[14px] text-muted-foreground transition-colors outline-none select-none hover:bg-input/50 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:flex w-[clamp(10rem,24vw,22rem)]"
      >
        <Search className="size-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate">Search…</span>
        {isMac === null ? null : (
          <kbd className="shrink-0 rounded border border-border bg-muted/50 px-1 font-sans text-[11px] leading-4">
            {isMac ? "⌘K" : "Ctrl K"}
          </kbd>
        )}
      </button>
      <Button
        ref={mobileTriggerRef}
        type="button"
        variant="ghost"
        size="icon-lg"
        aria-label="Search"
        aria-haspopup="dialog"
        onClick={onMobileTap}
        className="md:hidden"
      >
        <Search aria-hidden />
      </Button>

      <Dialog
        open={open && !isMobile}
        onOpenChange={(next) => {
          if (!next) requestClose();
        }}
      >
        <DialogContent
          showCloseButton={false}
          data-search-palette=""
          initialFocus={initialFocus}
          finalFocus={finalFocus}
          className="top-[10vh] translate-y-0 gap-0 overflow-hidden rounded-xl p-0 sm:max-w-3xl motion-reduce:animate-none motion-reduce:transition-none motion-reduce:data-open:animate-none motion-reduce:data-closed:animate-none"
        >
          <DialogTitle className="sr-only">Search</DialogTitle>
          <DialogDescription className="sr-only">
            Search your holdings, pages and actions.
          </DialogDescription>
          {panel("desktop")}
        </DialogContent>
      </Dialog>

      <Sheet
        open={open && isMobile}
        onOpenChange={(next) => {
          if (!next) requestClose();
        }}
      >
        <SheetContent
          side="top"
          showCloseButton={false}
          data-search-palette=""
          initialFocus={initialFocus}
          finalFocus={finalFocus}
          className="inset-0 h-dvh w-full max-w-none gap-0 overflow-hidden rounded-none border-0 p-0 shadow-none duration-100 data-[side=top]:h-dvh data-[side=top]:border-b-0 data-[side=top]:data-ending-style:translate-y-0 data-[side=top]:data-starting-style:translate-y-0 motion-reduce:transition-none"
          style={viewport ? { top: viewport.top, height: viewport.height } : undefined}
        >
          <SheetTitle className="sr-only">Search</SheetTitle>
          <SheetDescription className="sr-only">
            Search your holdings, pages and actions.
          </SheetDescription>
          {panel("mobile")}
        </SheetContent>
      </Sheet>
    </>
  );
}
