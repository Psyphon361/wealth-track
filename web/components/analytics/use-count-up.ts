"use client";

import { useEffect, useRef, useState } from "react";

const DURATION_MS = 600;

/** Eases a number from its last shown value to `target` (about 600 ms; instant with reduced motion). */
export function useCountUp(target: number): number {
  const [value, setValue] = useState(0);
  const shown = useRef(0);

  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const from = shown.current;
    const duration = reduced ? 0 : DURATION_MS;
    let start: number | null = null;
    let raf = 0;
    const tick = (now: number) => {
      start ??= now;
      const t = duration === 0 ? 1 : Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = from + (target - from) * eased;
      shown.current = next;
      setValue(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return value;
}
