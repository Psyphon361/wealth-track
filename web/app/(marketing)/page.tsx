import type { Metadata } from "next";
import { AuthCta } from "@/components/landing/auth-cta";
import { Features } from "@/components/landing/features";
import { Hero } from "@/components/landing/hero";
import { Nav } from "@/components/landing/nav";

export const metadata: Metadata = {
  title: "Wealth Tracker — all your wealth in one place",
  description:
    "Track fixed deposits, recurring deposits, stocks, bonds and mutual funds in one quiet dashboard, valued every day in rupees.",
};

export default function LandingPage() {
  return (
    <>
      <Nav cta={<AuthCta />} />
      <main>
        <Hero />
        <Features />
      </main>
    </>
  );
}
