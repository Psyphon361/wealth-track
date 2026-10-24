/** Strip everything except digits and one decimal point; cap decimal places. */
export function sanitizeNumber(input: string, decimals: number): string {
  let out = "";
  let seenDot = false;
  for (const ch of input) {
    if (ch >= "0" && ch <= "9") out += ch;
    else if (ch === "." && decimals > 0 && !seenDot) {
      seenDot = true;
      out += ch;
    }
  }
  const dot = out.indexOf(".");
  if (dot !== -1) out = out.slice(0, dot + 1 + decimals);
  return out.replace(/^0+(?=\d)/, "");
}

/** Group the integer part Indian-style (12,34,567); decimals kept as typed. */
export function formatIndianNumber(raw: string): string {
  const dot = raw.indexOf(".");
  const int = dot === -1 ? raw : raw.slice(0, dot);
  const rest = dot === -1 ? "" : raw.slice(dot);
  const grouped = int.replace(/\B(?=(\d\d)*\d{3}(?!\d))/g, ",");
  return grouped + rest;
}

/** Index in `formatted` just after the n-th digit/decimal-point character. */
export function caretAfterChars(formatted: string, n: number): number {
  if (n <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < formatted.length; i++) {
    if (formatted[i] !== ",") seen++;
    if (seen === n) return i + 1;
  }
  return formatted.length;
}
