import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Aurora } from "./aurora";
import { Wordmark } from "./nav";
import { Reveal } from "./reveal";

export function ClosingCta() {
  return (
    <section className="relative px-4 py-28 text-center">
      <Aurora className="h-full opacity-50" />
      <Reveal className="mx-auto max-w-6xl">
        <h2 className="text-3xl font-semibold tracking-tight md:text-4xl">Start tracking in minutes</h2>
        <Link href="/signup" className={cn(buttonVariants({ size: "lg" }), "mt-8 h-10 px-5 text-sm")}>
          Get started
        </Link>
      </Reveal>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-border px-4 py-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 text-xs text-muted-foreground sm:flex-row">
        <Wordmark />
        <span>© 2026 Wealth Tracker</span>
        <span>Made in India</span>
      </div>
    </footer>
  );
}
