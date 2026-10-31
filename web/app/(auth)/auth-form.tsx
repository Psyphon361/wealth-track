"use client";

import { useActionState, useEffect, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { Eye, EyeOff, Wallet } from "lucide-react";
import { z } from "zod";
import { clearAuthError, type AuthState } from "@/app/actions/auth";
import {
  EMAIL_ERROR,
  PASSWORD_MAX,
  PASSWORD_MAX_ERROR,
  PASSWORD_MIN,
  PASSWORD_MIN_ERROR,
  PASSWORD_REQUIRED_ERROR,
} from "@/components/forms/schema";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

const INITIAL: AuthState = { message: null, description: null };

const emailSchema = z.string().trim().pipe(z.email(EMAIL_ERROR));
const loginPasswordSchema = z.string().min(1, PASSWORD_REQUIRED_ERROR);
const signupPasswordSchema = z
  .string()
  .min(PASSWORD_MIN, PASSWORD_MIN_ERROR)
  .max(PASSWORD_MAX, PASSWORD_MAX_ERROR);

function GoogleLogo() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden="true" className="size-4">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

type Mode = "login" | "signup";
type Errors = { email?: string; password?: string };

export function AuthForm({
  mode,
  next,
  action: serverAction,
  initialError = null,
}: {
  mode: Mode;
  next: string;
  action: (prev: AuthState, formData: FormData) => Promise<AuthState>;
  initialError?: { message: string; description: string | null } | null;
}) {
  const [state, action, pending] = useActionState(serverAction, INITIAL);
  const [email, setEmail] = useState("");
  const [localErrors, setLocalErrors] = useState<Errors>({});
  const [showPassword, setShowPassword] = useState(false);
  // Error handed over by the Google OAuth routes; kept in state so it survives clearing the cookie.
  const [oauthError] = useState(initialError);
  useEffect(() => {
    if (initialError) void clearAuthError();
  }, [initialError]);
  const shown = state.message ? state : oauthError;
  const isLogin = mode === "login";
  const passwordSchema = isLogin ? loginPasswordSchema : signupPasswordSchema;
  const errors: Errors = { ...state.fieldErrors, ...localErrors };

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    const data = new FormData(event.currentTarget);
    const emailResult = emailSchema.safeParse(data.get("email") ?? "");
    const passwordResult = passwordSchema.safeParse(data.get("password") ?? "");
    const found: Errors = {};
    if (!emailResult.success) found.email = emailResult.error.issues[0].message;
    if (!passwordResult.success) found.password = passwordResult.error.issues[0].message;
    setLocalErrors(found);
    if (found.email || found.password) event.preventDefault();
  }

  const query = next !== "/" ? `?next=${encodeURIComponent(next)}` : "";

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Wallet className="size-4" />
          </span>
          Wealth Tracker
        </CardTitle>
      </CardHeader>
      <CardContent>
        <a
          href={`/auth/google/start${query}`}
          className={cn(buttonVariants({ variant: "outline" }), "w-full")}
        >
          <GoogleLogo />
          Continue with Google
        </a>
        <div className="my-3 flex items-center gap-3 text-xs text-muted-foreground">
          <span className="h-px flex-1 bg-border" />
          or
          <span className="h-px flex-1 bg-border" />
        </div>
        <form action={action} onSubmit={onSubmit} noValidate className="space-y-3">
          <input type="hidden" name="next" value={next} />
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              name="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              aria-invalid={errors.email ? true : undefined}
              autoFocus
            />
            {errors.email ? <p className="text-xs text-destructive">{errors.email}</p> : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <div className="relative">
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                name="password"
                autoComplete={isLogin ? "current-password" : "new-password"}
                aria-invalid={errors.password ? true : undefined}
                className="pr-9"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                className="absolute top-1/2 right-0.5 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword((shown) => !shown)}
              >
                {showPassword ? <EyeOff /> : <Eye />}
              </Button>
            </div>
            {errors.password ? (
              <p className="text-xs text-destructive">{errors.password}</p>
            ) : null}
          </div>
          {shown?.message ? (
            <div role="alert" className="space-y-0.5 text-xs text-destructive">
              <p className="font-medium">{shown.message}</p>
              {shown.description ? <p>{shown.description}</p> : null}
            </div>
          ) : null}
          <Button type="submit" className="w-full" disabled={pending}>
            {isLogin
              ? pending
                ? "Signing in…"
                : "Sign in"
              : pending
                ? "Creating account…"
                : "Create account"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            {isLogin ? (
              <Link href={`/signup${query}`} className="underline underline-offset-2">
                Create an account
              </Link>
            ) : (
              <Link href={`/login${query}`} className="underline underline-offset-2">
                Already have an account? Log in
              </Link>
            )}
          </p>
          <p className="text-center text-xs text-muted-foreground">
            <Link href="/" className="underline underline-offset-2">
              ← Back to home
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
