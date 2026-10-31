import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Aurora } from "./aurora";
import { ProductPreview } from "./product-preview";

export function Hero() {
  return (
    <section className="relative px-4 pt-16 pb-20 sm:pt-24">
      <Aurora />
      <div className="mx-auto max-w-6xl text-center">
        <span className="inline-flex items-center gap-2 rounded-full border border-border bg-card/50 px-3 py-1 text-xs text-muted-foreground backdrop-blur">
          <span className="size-1.5 rounded-full bg-gain" />
          Built for Indian investors
        </span>
        <h1 className="mx-auto mt-6 max-w-3xl text-5xl font-semibold tracking-tighter text-balance md:text-6xl">
          All your wealth.{" "}
          <span className="bg-gradient-to-r from-gain to-[oklch(0.75_0.11_190)] bg-clip-text text-transparent">
            One quiet dashboard.
          </span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-base text-muted-foreground text-balance">
          FDs, RDs, stocks, bonds and mutual funds — valued every day, in ₹.
        </p>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link href="/signup" className={cn(buttonVariants({ size: "lg" }), "h-10 px-5 text-sm")}>
            Get started
          </Link>
          <Link
            href="/login"
            className={cn(buttonVariants({ variant: "outline", size: "lg" }), "h-10 px-5 text-sm")}
          >
            Log in
          </Link>
        </div>
        <ProductPreview />
      </div>
    </section>
  );
}
