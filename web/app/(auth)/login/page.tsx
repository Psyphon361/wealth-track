import { Suspense } from "react";
import { login } from "@/app/actions/auth";
import { safeNext } from "@/lib/auth";
import { AuthForm } from "../auth-form";

async function Form({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const params = await searchParams;
  const raw = params.next;
  return <AuthForm mode="login" action={login} next={safeNext(typeof raw === "string" ? raw : null)} />;
}

export default function LoginPage({ searchParams }: PageProps<"/login">) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <Suspense fallback={null}>
        <Form searchParams={searchParams} />
      </Suspense>
    </main>
  );
}
