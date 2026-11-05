const CSS = `
@keyframes wt-top-progress {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(250%); }
}
.wt-top-progress-bar { animation: wt-top-progress 1.2s ease-in-out infinite; }
@media (prefers-reduced-motion: reduce) {
  .wt-top-progress-bar { animation: none; transform: none; width: 100%; opacity: 0.6; }
}
`;

/** Thin indeterminate progress bar along the top edge of a relatively positioned card. */
export function TopProgress({ active }: { active: boolean }) {
  if (!active) return null;
  return (
    <div
      className="pointer-events-none absolute inset-x-0 top-0 h-0.5 overflow-hidden rounded-t-xl"
      role="progressbar"
      aria-label="Loading…"
    >
      <style href="wt-top-progress" precedence="default">{CSS}</style>
      <div className="wt-top-progress-bar h-full w-2/5 bg-primary" />
    </div>
  );
}
