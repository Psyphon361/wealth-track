"use client";

import { useEffect, useRef } from "react";

const AURORA_CSS = `
.lp-aurora {
  --mx: 0;
  --my: 0;
  --sx: 50%;
  --sy: 30%;
  --so: 0;
}
.lp-ray {
  position: absolute;
  top: -10%;
  left: 50%;
  height: 120%;
  transform-origin: 50% 0;
  transform: translateX(calc(var(--mx) * var(--shift, -1vw))) rotate(calc(var(--r) + var(--mx) * var(--tilt, 3deg)));
  background: linear-gradient(to bottom, oklch(0.85 0.09 163 / var(--a)) 0%, oklch(0.85 0.09 163 / calc(var(--a) * 0.4)) 45%, transparent 85%);
  will-change: transform;
}
.lp-spot {
  position: absolute;
  inset: 0;
  opacity: var(--so);
  background: radial-gradient(420px circle at var(--sx) var(--sy), oklch(0.85 0.09 163 / 0.09), transparent 70%);
}
@media (prefers-reduced-motion: reduce) {
  .lp-ray { will-change: auto; }
  .lp-reveal-hidden { opacity: 1 !important; transform: none !important; transition: none !important; }
}
`;

const RAYS = [
  { r: "-24deg", w: "9vw", a: 0.09, blur: 28, tilt: "4deg", shift: "-1.5vw" },
  { r: "-9deg", w: "14vw", a: 0.13, blur: 36, tilt: "3deg", shift: "-1vw" },
  { r: "8deg", w: "12vw", a: 0.12, blur: 32, tilt: "3.5deg", shift: "-1.2vw" },
  { r: "23deg", w: "8vw", a: 0.08, blur: 26, tilt: "4.5deg", shift: "-1.8vw" },
];

export function Aurora({ className = "h-screen" }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    const parent = el?.parentElement;
    if (!el || !parent) return;
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (coarse || reduced) return;

    const target = { x: 0, y: 0, sx: 0, sy: 0, o: 0 };
    const cur = { x: 0, y: 0, sx: 0, sy: 0, o: 0 };
    let raf = 0;
    let first = true;

    const tick = () => {
      const k = 0.08;
      cur.x += (target.x - cur.x) * k;
      cur.y += (target.y - cur.y) * k;
      cur.sx += (target.sx - cur.sx) * 0.2;
      cur.sy += (target.sy - cur.sy) * 0.2;
      cur.o += (target.o - cur.o) * 0.08;
      el.style.setProperty("--mx", cur.x.toFixed(4));
      el.style.setProperty("--my", cur.y.toFixed(4));
      el.style.setProperty("--sx", `${cur.sx.toFixed(1)}px`);
      el.style.setProperty("--sy", `${cur.sy.toFixed(1)}px`);
      el.style.setProperty("--so", cur.o.toFixed(4));
      const settled =
        Math.abs(target.x - cur.x) < 0.001 &&
        Math.abs(target.y - cur.y) < 0.001 &&
        Math.abs(target.sx - cur.sx) < 0.5 &&
        Math.abs(target.sy - cur.sy) < 0.5 &&
        Math.abs(target.o - cur.o) < 0.001;
      raf = settled ? 0 : requestAnimationFrame(tick);
    };
    const kick = () => {
      if (!raf) raf = requestAnimationFrame(tick);
    };

    const onMove = (e: PointerEvent) => {
      const rect = parent.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const inside = px >= 0 && py >= 0 && px <= rect.width && py <= rect.height;
      if (inside) {
        target.x = (px / rect.width) * 2 - 1;
        target.y = (py / rect.height) * 2 - 1;
        target.sx = px;
        target.sy = py;
        target.o = 1;
        if (first) {
          cur.sx = px;
          cur.sy = py;
          first = false;
        }
      } else {
        target.x = 0;
        target.y = 0;
        target.o = 0;
      }
      kick();
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <div
      ref={ref}
      aria-hidden
      className={`lp-aurora pointer-events-none absolute inset-x-0 top-0 -z-10 overflow-hidden ${className}`}
      style={{
        maskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
      }}
    >
      <style href="landing-aurora" precedence="default">{AURORA_CSS}</style>
      {RAYS.map((ray, i) => (
        <div
          key={i}
          className="lp-ray"
          style={
            {
              width: ray.w,
              marginLeft: `calc(${ray.w} / -2)`,
              filter: `blur(${ray.blur}px)`,
              "--r": ray.r,
              "--a": ray.a,
              "--tilt": ray.tilt,
              "--shift": ray.shift,
            } as React.CSSProperties
          }
        />
      ))}
      <div className="lp-spot" />
      <svg className="absolute inset-0 size-full opacity-[0.05]" xmlns="http://www.w3.org/2000/svg">
        <filter id="aurora-grain">
          <feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter="url(#aurora-grain)" />
      </svg>
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at 50% 30%, transparent 40%, var(--background) 100%)",
        }}
      />
    </div>
  );
}
