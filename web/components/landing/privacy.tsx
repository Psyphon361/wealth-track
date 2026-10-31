import { ShieldCheck } from "lucide-react";
import { Reveal } from "./reveal";

const points = [
  "Your CAS file and password are read in memory and never stored.",
  "Invite-only, one person per account.",
  "No ads, no broker upsell.",
];

export function Privacy() {
  return (
    <section className="px-4 py-12">
      <Reveal className="mx-auto max-w-6xl">
        <div className="flex flex-col gap-6 rounded-2xl border border-border bg-card/60 p-6 sm:p-8 md:flex-row md:items-center md:gap-10">
          <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary/15 text-primary">
            <ShieldCheck className="size-6" />
          </span>
          <div className="md:w-56 md:shrink-0">
            <h2 className="text-xl font-semibold tracking-tight">Your data stays yours</h2>
          </div>
          <ul className="space-y-2 text-muted-foreground">
            {points.map((p) => (
              <li key={p} className="flex gap-2">
                <span className="mt-2 size-1 shrink-0 rounded-full bg-gain" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </Reveal>
    </section>
  );
}
