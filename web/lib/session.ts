export const SESSION_COOKIE = "wt_session";
export const SESSION_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export type GateMode = "disabled" | "enabled" | "misconfigured";

/** Server-only. Decides whether the password gate is active. */
export function gateMode(): GateMode {
  const password = process.env.APP_PASSWORD;
  const secret = process.env.SESSION_SECRET;
  if (!password) {
    return process.env.NODE_ENV === "production" ? "misconfigured" : "disabled";
  }
  if (!secret) return "misconfigured";
  return "enabled";
}

const encoder = new TextEncoder();

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf), (b) => b.toString(16).padStart(2, "0")).join("");
}

async function hmac(secret: string, message: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return toHex(await crypto.subtle.sign("HMAC", key, encoder.encode(message)));
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionToken(secret: string): Promise<string> {
  const exp = Math.floor(Date.now() / 1000) + SESSION_MAX_AGE_SECONDS;
  return `${exp}.${await hmac(secret, String(exp))}`;
}

export async function verifySessionToken(
  token: string | undefined,
  secret: string | undefined,
): Promise<boolean> {
  if (!token || !secret) return false;
  const [expStr, sig, ...rest] = token.split(".");
  if (!expStr || !sig || rest.length > 0 || !/^\d+$/.test(expStr)) return false;
  if (Number(expStr) <= Math.floor(Date.now() / 1000)) return false;
  return safeEqual(sig, await hmac(secret, expStr));
}

/** Constant-time password comparison (compares SHA-256 digests). */
export async function passwordMatches(input: string, expected: string): Promise<boolean> {
  const [a, b] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(input)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return safeEqual(toHex(a), toHex(b));
}

/** Only allow same-origin relative paths. */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return "/";
  }
  return next;
}
