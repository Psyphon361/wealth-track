/** Normalised text plus, for every normalised UTF-16 unit, the span it came from in the original. */
export interface Normalized {
  text: string;
  starts: number[];
  ends: number[];
}

const MARKS = new RegExp("\\p{M}", "gu");
const WORD_CHAR = new RegExp("[\\p{L}\\p{N}]", "u");

/**
 * Lowercase, strip diacritics, "&" becomes "and", punctuation becomes a space, spaces collapsed
 * and trimmed. The index map lets callers translate a hit back to the original string.
 */
export function normalizeMapped(input: string): Normalized {
  let text = "";
  const starts: number[] = [];
  const ends: number[] = [];
  let i = 0;
  for (const ch of input) {
    const start = i;
    i += ch.length;
    const folded = ch.toLowerCase().normalize("NFD").replace(MARKS, "");
    if (folded === "") {
      // A combining mark: keep it inside the previous character's span.
      if (ends.length) ends[ends.length - 1] = i;
      continue;
    }
    for (const c of ch === "&" ? " and " : folded) {
      const out = WORD_CHAR.test(c) ? c : " ";
      if (out === " " && (text === "" || text.endsWith(" "))) continue;
      for (let k = 0; k < out.length; k++) {
        starts.push(start);
        ends.push(i);
      }
      text += out;
    }
  }
  if (text.endsWith(" ")) {
    text = text.slice(0, -1);
    starts.pop();
    ends.pop();
  }
  return { text, starts, ends };
}

export function normalize(input: string): string {
  return normalizeMapped(input).text;
}

export function tokenize(input: string): string[] {
  const text = normalize(input);
  return text === "" ? [] : text.split(" ");
}

/** Normalised form without spaces, for ids ("INE 002A01018" equals "INE002A01018"). */
export function compact(input: string): string {
  return normalize(input).replace(/ /g, "");
}
