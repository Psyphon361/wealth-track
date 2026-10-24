import { Suspense } from "react";
import { safeNext } from "@/lib/session";
import { LoginForm } from "./login-form";

async function Form({ searchParams }: Pick<PageProps<"/login">, "searchParams">) {
  const params = await searchParams;
  const raw = params.next;
  return <LoginForm next={safeNext(typeof raw === "string" ? raw : null)} />;
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
