"use client";

import { useSyncExternalStore } from "react";

function subscribeNever(): () => void {
  return () => {};
}

function detectMac(): boolean {
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
  const platform = nav.userAgentData?.platform ?? nav.platform ?? "";
  return /mac|iphone|ipad|ipod/i.test(platform);
}

/** true on Apple platforms, false elsewhere, null on the server and during hydration. */
export function useIsMac(): boolean | null {
  return useSyncExternalStore(subscribeNever, detectMac, () => null);
}

export interface ViewportBox {
  /** Visible height in CSS pixels (shrinks when the on-screen keyboard is up). */
  height: number;
  /** Distance of the visible area from the top of the layout viewport. */
  top: number;
  keyboardOpen: boolean;
}

let box: ViewportBox | null = null;

function readViewport(): ViewportBox | null {
  const vv = window.visualViewport;
  if (!vv) return null;
  const height = Math.round(vv.height);
  const top = Math.round(vv.offsetTop);
  const keyboardOpen = window.innerHeight - height - top > 80;
  if (!box || box.height !== height || box.top !== top || box.keyboardOpen !== keyboardOpen) {
    box = { height, top, keyboardOpen };
  }
  return box;
}

function subscribeViewport(onChange: () => void): () => void {
  const vv = window.visualViewport;
  if (!vv) return () => {};
  vv.addEventListener("resize", onChange);
  vv.addEventListener("scroll", onChange);
  return () => {
    vv.removeEventListener("resize", onChange);
    vv.removeEventListener("scroll", onChange);
  };
}

/** The visual viewport (null when unsupported: callers fall back to 100dvh). */
export function useVisualViewport(): ViewportBox | null {
  return useSyncExternalStore(subscribeViewport, readViewport, () => null);
}
