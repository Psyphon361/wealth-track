import {
  STATUS_LABELS,
  instalmentsText,
  isNextSkipped,
  nextText,
} from "@/lib/sip";
import type { Sip } from "@/lib/types";

const DOT: Record<Sip["status"], string> = {
  active: "bg-gain",
  paused: "bg-amber-400",
  stopped: "bg-muted-foreground",
};

/** Status pill with a coloured dot: Active (green), Paused (amber), Cancelled (muted). */
export function SipBadge({ status }: { status: Sip["status"] }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-muted/50 px-2 py-0.5 text-xs whitespace-nowrap">
      <span
        className={`size-1.5 rounded-full ${DOT[status]}`}
        aria-hidden="true"
      />
      <span className={status === "active" ? undefined : "text-muted-foreground"}>
        {STATUS_LABELS[status]}
      </span>
    </span>
  );
}

/** "Next 5 Dec 2026 · 11 instalments · ₹55,000 invested"; the skip is highlighted. */
export function SipProgressLine({ sip }: { sip: Sip }) {
  const skipping = sip.status === "active" && isNextSkipped(sip);
  return (
    <p className="text-xs text-muted-foreground">
      <span className={skipping ? "num text-amber-300" : "num"}>
        {nextText(sip)}
      </span>{" "}
      · <span className="num">{instalmentsText(sip)}</span>
    </p>
  );
}
