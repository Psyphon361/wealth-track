const AURORA_CSS = `
@keyframes lp-aurora-a {
  from { transform: translate3d(-8%, -4%, 0) rotate(-8deg) scale(1); }
  to { transform: translate3d(10%, 8%, 0) rotate(10deg) scale(1.2); }
}
@keyframes lp-aurora-b {
  from { transform: translate3d(6%, 6%, 0) rotate(12deg) scale(1.1); }
  to { transform: translate3d(-12%, -6%, 0) rotate(-6deg) scale(0.9); }
}
@keyframes lp-aurora-c {
  from { transform: translate3d(-6%, 8%, 0) rotate(0deg) scale(0.9); }
  to { transform: translate3d(8%, -8%, 0) rotate(20deg) scale(1.15); }
}
@keyframes lp-aurora-d {
  from { transform: translate3d(10%, -6%, 0) rotate(-14deg) scale(1.05); }
  to { transform: translate3d(-8%, 6%, 0) rotate(8deg) scale(1.25); }
}
.lp-blob {
  position: absolute;
  border-radius: 9999px;
  mix-blend-mode: screen;
  will-change: transform;
  animation-timing-function: ease-in-out;
  animation-direction: alternate;
  animation-iteration-count: infinite;
}
.lp-blob-a { animation-name: lp-aurora-a; }
.lp-blob-b { animation-name: lp-aurora-b; }
.lp-blob-c { animation-name: lp-aurora-c; }
.lp-blob-d { animation-name: lp-aurora-d; }
@media (prefers-reduced-motion: reduce) {
  .lp-blob { animation: none !important; }
  .lp-reveal-hidden { opacity: 1 !important; transform: none !important; transition: none !important; }
}
`;

export function Aurora({ className = "h-screen" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`pointer-events-none absolute inset-x-0 top-0 -z-10 overflow-hidden ${className}`}
      style={{
        maskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(to bottom, black 55%, transparent 100%)",
      }}
    >
      <style href="landing-aurora" precedence="default">{AURORA_CSS}</style>
      <div
        className="lp-blob lp-blob-a -top-[15%] -left-[15%] h-[55vh] w-[80vw]"
        style={{
          background: "oklch(0.45 0.11 165)",
          opacity: 0.45,
          filter: "blur(110px)",
          animationDuration: "32s",
        }}
      />
      <div
        className="lp-blob lp-blob-b top-[5%] left-[25%] h-[50vh] w-[70vw]"
        style={{
          background: "oklch(0.696 0.15 163)",
          opacity: 0.3,
          filter: "blur(120px)",
          animationDuration: "41s",
          animationDelay: "-9s",
        }}
      />
      <div
        className="lp-blob lp-blob-c top-[-10%] right-[-15%] h-[60vh] w-[65vw]"
        style={{
          background: "oklch(0.62 0.1 190)",
          opacity: 0.32,
          filter: "blur(100px)",
          animationDuration: "27s",
          animationDelay: "-14s",
        }}
      />
      <div
        className="lp-blob lp-blob-d top-[30%] left-[-10%] h-[40vh] w-[60vw]"
        style={{
          background: "oklch(0.35 0.09 170)",
          opacity: 0.4,
          filter: "blur(90px)",
          animationDuration: "45s",
          animationDelay: "-22s",
        }}
      />
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
