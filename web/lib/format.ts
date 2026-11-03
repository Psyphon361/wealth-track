const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatINR(n: number): string {
  return inr.format(n);
}

const inrWhole = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

/** Whole rupees with Indian grouping, no paise: ₹2,60,970. */
export function formatINRWhole(n: number): string {
  return inrWhole.format(n);
}

export function formatPct(n: number): string {
  return `${n.toFixed(2)}%`;
}

export function formatDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** ISO 8601 timestamp as IST, e.g. "30 Oct, 2:12 pm". */
export function formatIstDateTime(iso: string): string {
  const parts = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  }).formatToParts(new Date(iso));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("day")} ${get("month")}, ${get("hour")}:${get("minute")} ${get("dayPeriod").toLowerCase()}`;
}

function trim1(n: number): string {
  return n.toFixed(1).replace(/\.0$/, "");
}

/** Compact Indian units for axes: ₹950, ₹12K, ₹12.4L, ₹1.2Cr. */
export function formatINRCompact(n: number): string {
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}₹${trim1(a / 1e7)}Cr`;
  if (a >= 1e5) return `${sign}₹${trim1(a / 1e5)}L`;
  if (a >= 1e3) return `${sign}₹${trim1(a / 1e3)}K`;
  return `${sign}₹${Math.round(a)}`;
}
