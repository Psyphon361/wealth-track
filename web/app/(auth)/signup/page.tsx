import { Suspense } from "react";
import { cookies } from "next/headers";
import { signup } from "@/app/actions/auth";
import { AUTH_ERROR_COOKIE, parseAuthError, safeNext } from "@/lib/auth";
import { AuthForm } from "../auth-form";

async function Form({ searchParams }: Pick<PageProps<"/signup">, "searchParams">) {
  const params = await searchParams;
  const raw = params.next;
  const store = await cookies();
  const initialError = parseAuthError(store.get(AUTH_ERROR_COOKIE)?.value);
  return (
    <AuthForm
      mode="signup"
      action={signup}
      next={safeNext(typeof raw === "string" ? raw : null)}
      initialError={initialError}
    />
  );
}

export default function SignupPage({ searchParams }: PageProps<"/signup">) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Suspense fallback={null}>
        <Form searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
