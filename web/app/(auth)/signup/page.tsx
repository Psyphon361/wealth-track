import { Suspense } from "react";
import { signup } from "@/app/actions/auth";
import { safeNext } from "@/lib/auth";
import { AuthForm } from "../auth-form";

async function Form({ searchParams }: Pick<PageProps<"/signup">, "searchParams">) {
  const params = await searchParams;
  const raw = params.next;
  return <AuthForm mode="signup" action={signup} next={safeNext(typeof raw === "string" ? raw : null)} />;
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
