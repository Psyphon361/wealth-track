import Link from "next/link";
import { cookies } from "next/headers";
import { Suspense } from "react";
import { buttonVariants } from "@/components/ui/button";
import { REFRESH_COOKIE } from "@/lib/auth";
import { cn } from "@/lib/utils";

type Variant = "nav" | "hero";

const primary = "bg-foreground text-background hover:bg-foreground/90";
const navPrimary = cn(buttonVariants(), primary);
const heroSize = cn(buttonVariants({ size: "lg" }), "h-10 px-5 text-sm", primary);
const heroOutline = cn(buttonVariants({ variant: "outline", size: "lg" }), "h-10 px-5 text-sm");

function SignedOut({ variant }: { variant: Variant }) {
  if (variant === "nav") {
    return (
      <>
        <Link href="/login" className={buttonVariants({ variant: "ghost" })}>
          Log in
        </Link>
        <Link href="/signup" className={navPrimary}>
          Get started
        </Link>
      </>
    );
  }
  return (
    <>
      <Link href="/signup" className={heroSize}>
        Get started
      </Link>
      <Link href="/login" className={heroOutline}>
        Log in
      </Link>
    </>
  );
}

async function CtaByAuth({ variant }: { variant: Variant }) {
  const signedIn = Boolean((await cookies()).get(REFRESH_COOKIE)?.value);
  if (!signedIn) return <SignedOut variant={variant} />;
  return (
    <Link href="/dashboard" className={variant === "nav" ? navPrimary : heroSize}>
      Open app
    </Link>
  );
}

/** Auth-aware landing buttons. Reads the cookie inside Suspense so the page stays static. */
export function AuthCta({ variant }: { variant: Variant }) {
  return (
    <Suspense fallback={<SignedOut variant={variant} />}>
      <CtaByAuth variant={variant} />
    </Suspense>
  );
}
