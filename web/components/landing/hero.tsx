import { Aurora } from "./aurora";
import { ProductPreview } from "./product-preview";

export function Hero() {
  return (
    <section className="relative px-4 pt-10 pb-12 sm:pt-14">
      <Aurora />
      <div className="mx-auto max-w-6xl text-center">
        <h1 className="mx-auto max-w-3xl text-5xl font-semibold tracking-tighter text-balance md:text-6xl">
          All your wealth.{" "}
          <span className="bg-gradient-to-r from-foreground to-muted-foreground bg-clip-text text-transparent">
            One quiet dashboard.
          </span>
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-base text-muted-foreground text-balance">
          FDs, RDs, stocks, bonds and mutual funds — valued every day, in ₹.
        </p>
        <ProductPreview />
      </div>
    </section>
  );
}
