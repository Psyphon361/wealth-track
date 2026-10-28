"use client";

import { useActionState, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { Eye, EyeOff, Wallet } from "lucide-react";
import { z } from "zod";
import type { AuthState } from "@/app/actions/auth";
import {
  EMAIL_ERROR,
  PASSWORD_MAX,
  PASSWORD_MAX_ERROR,
  PASSWORD_MIN,
  PASSWORD_MIN_ERROR,
  PASSWORD_REQUIRED_ERROR,
} from "@/components/forms/schema";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const INITIAL: AuthState = { message: null, description: null };

const emailSchema = z.string().trim().pipe(z.email(EMAIL_ERROR));
const loginPasswordSchema = z.string().min(1, PASSWORD_REQUIRED_ERROR);
const signupPasswordSchema = z
  .string()
  .min(PASSWORD_MIN, PASSWORD_MIN_ERROR)
  .max(PASSWORD_MAX, PASSWORD_MAX_ERROR);

type Mode = "login" | "signup";
type Errors = { email?: string; password?: string };

export function AuthForm({
  mode,
  next,
  action: serverAction,
}: {
  mode: Mode;
  next: string;
  action: (prev: AuthState, formData: FormData) => Promise<AuthState>;
}) {
  const [state, action, pending] = useActionState(serverAction, INITIAL);
  const [email, setEmail] = useState("");
  const [localErrors, setLocalErrors] = useState<Errors>({});
  const [showPassword, setShowPassword] = useState(false);
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
          {state.message ? (
            <div role="alert" className="space-y-0.5 text-xs text-destructive">
              <p className="font-medium">{state.message}</p>
              {state.description ? <p>{state.description}</p> : null}
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
        </form>
      </CardContent>
    </Card>
  );
}
