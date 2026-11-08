// Name helpers. Messages and rules match api/app/routers/auth.py (clean_name).
export const NAME_REQUIRED_ERROR = "Enter your name";
export const NAME_MAX = 80;
export const NAME_MAX_ERROR = "Name is too long (80 characters at most)";

/** Trim and collapse spaces; returns the cleaned name or the shared error message. */
export function cleanName(value: string): { name: string; error: null } | { name: null; error: string } {
  const name = value.split(/\s+/).filter(Boolean).join(" ");
  if (!name) return { name: null, error: NAME_REQUIRED_ERROR };
  if ([...name].length > NAME_MAX) return { name: null, error: NAME_MAX_ERROR };
  return { name, error: null };
}

function firstChar(word: string): string {
  return ([...word][0] ?? "").toUpperCase();
}

/** Avatar initials: first letters of the first and last words, else the email's first letter. */
export function initials(fullName: string | null | undefined, email: string): string {
  const words = (fullName ?? "").split(/\s+/).filter(Boolean);
  if (words.length === 0) return firstChar(email.trim());
  if (words.length === 1) return firstChar(words[0]);
  return firstChar(words[0]) + firstChar(words[words.length - 1]);
}
