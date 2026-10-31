import Link from "next/link";
import { cookies } from "next/headers";
import { Suspense } from "react";
import { buttonVariants } from "@/components/ui/button";
import { REFRESH_COOKIE } from "@/lib/auth";
import { cn } from "@/lib/utils";

const primary = cn(buttonVariants(), "bg-foreground text-background hover:bg-foreground/90");

function SignedOut() {
  return (
    <>
      <Link href="/login" className={buttonVariants({ variant: "ghost" })}>
        Log in
      </Link>
      <Link href="/signup" className={primary}>
        Get started
      </Link>
    </>
  );
}

async function CtaByAuth() {
  const signedIn = Boolean((await cookies()).get(REFRESH_COOKIE)?.value);
  if (!signedIn) return <SignedOut />;
  return (
    <Link href="/dashboard" className={primary}>
      Open app
    </Link>
  );
}

/** Auth-aware nav buttons. Reads the cookie inside Suspense so the page stays static. */
export function AuthCta() {
  return (
    <Suspense fallback={<SignedOut />}>
      <CtaByAuth />
    </Suspense>
  );
}
