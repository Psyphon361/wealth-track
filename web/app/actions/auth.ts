"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  createSessionToken,
  gateMode,
  passwordMatches,
  safeNext,
} from "@/lib/session";

export type LoginState = { error: string | null };

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const mode = gateMode();
  if (mode === "disabled") redirect("/");
  const password = process.env.APP_PASSWORD;
  const secret = process.env.SESSION_SECRET;
  if (mode === "misconfigured" || !password || !secret) {
    return { error: "Server auth is not configured." };
  }

  const input = formData.get("password");
  const next = formData.get("next");
  const ok = typeof input === "string" && (await passwordMatches(input, password));
  if (!ok) {
    await new Promise((resolve) => setTimeout(resolve, 800));
    return { error: "Incorrect password." };
  }

  const store = await cookies();
  store.set(SESSION_COOKIE, await createSessionToken(secret), {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_SECONDS,
  });
  redirect(safeNext(typeof next === "string" ? next : null));
}

export async function logout(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  redirect("/login");
}
