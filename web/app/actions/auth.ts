"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  REFRESH_COOKIE,
  apiAuthFetch,
  clearAuthCookies,
  safeNext,
  setAuthCookies,
  type TokenResponse,
} from "@/lib/auth";

export type AuthState = {
  message: string | null;
  description: string | null;
  fieldErrors?: { email?: string; password?: string };
};

const INITIAL_OK: AuthState = { message: null, description: null };

async function submit(path: "login" | "signup", formData: FormData): Promise<AuthState> {
  const email = formData.get("email");
  const password = formData.get("password");
  const next = formData.get("next");

  let res: Response;
  try {
    res = await apiAuthFetch(path, {
      email: typeof email === "string" ? email.trim() : "",
      password: typeof password === "string" ? password : "",
    });
  } catch {
    return {
      message: "Couldn't reach the server",
      description: "Check your connection and try again.",
    };
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }

  if (!res.ok) {
    const body = (data ?? {}) as {
      message?: string;
      description?: string;
      detail?: unknown;
    };
    const fieldErrors: NonNullable<AuthState["fieldErrors"]> = {};
    if (res.status === 422 && Array.isArray(body.detail)) {
      for (const item of body.detail as { loc?: unknown[]; msg?: string }[]) {
        const field = item.loc?.[1];
        if ((field === "email" || field === "password") && item.msg && !fieldErrors[field]) {
          fieldErrors[field] = item.msg;
        }
      }
    }
    return {
      message: body.message ?? null,
      description: body.description ?? null,
      fieldErrors: Object.keys(fieldErrors).length > 0 ? fieldErrors : undefined,
    };
  }

  setAuthCookies(await cookies(), data as TokenResponse);
  redirect(safeNext(typeof next === "string" ? next : null));
  return INITIAL_OK;
}

export async function login(_prev: AuthState, formData: FormData): Promise<AuthState> {
  return submit("login", formData);
}

export async function signup(_prev: AuthState, formData: FormData): Promise<AuthState> {
  return submit("signup", formData);
}

export async function logout(): Promise<void> {
  const store = await cookies();
  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (refresh) {
    try {
      await apiAuthFetch("logout", { refresh_token: refresh });
    } catch {
      // Cookies are cleared regardless.
    }
  }
  clearAuthCookies(store);
  redirect("/login");
}
