import type { Metadata } from "next";
import { Features } from "@/components/landing/features";
import { ClosingCta, Footer } from "@/components/landing/footer";
import { Hero } from "@/components/landing/hero";
import { HowItWorks } from "@/components/landing/how-it-works";
import { Nav } from "@/components/landing/nav";
import { Privacy } from "@/components/landing/privacy";

export const metadata: Metadata = {
  title: "Wealth Tracker — all your wealth in one place",
  description:
    "Track fixed deposits, recurring deposits, stocks, bonds and mutual funds in one quiet dashboard, valued every day in rupees.",
};

export default function WelcomePage() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <Features />
        <HowItWorks />
        <Privacy />
        <ClosingCta />
      </main>
      <Footer />
    </>
  );
}
