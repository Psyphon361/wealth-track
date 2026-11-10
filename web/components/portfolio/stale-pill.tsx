/** Amber pill shown beside an as-of date the API flagged `stale`. */
export function StalePill() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/50 px-2 py-0.5 text-xs whitespace-nowrap">
      <span className="size-1.5 rounded-full bg-amber-400" aria-hidden="true" />
      <span className="text-amber-300">Stale</span>
    </span>
  );
}
