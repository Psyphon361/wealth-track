import { Reveal } from "./reveal";

const steps = [
  { title: "Sign in", text: "Create your account with email or Google." },
  { title: "Import your CAS or add holdings", text: "Upload a statement or enter assets by hand." },
  { title: "See everything valued daily", text: "Prices and NAVs refresh every night." },
];

export function HowItWorks() {
  return (
    <section className="px-4 py-20">
      <div className="mx-auto max-w-6xl">
        <Reveal className="text-center">
          <h2 className="text-3xl font-semibold tracking-tight">How it works</h2>
        </Reveal>
        <Reveal className="relative mt-12">
          <div
            aria-hidden
            className="absolute top-4 right-[16.6%] left-[16.6%] hidden h-px bg-gradient-to-r from-transparent via-border to-transparent md:block"
          />
          <ol className="grid gap-8 md:grid-cols-3">
            {steps.map((s, i) => (
              <li key={s.title} className="relative text-center">
                <span className="num relative mx-auto flex size-8 items-center justify-center rounded-full border border-primary/40 bg-background text-sm font-medium text-primary">
                  {i + 1}
                </span>
                <h3 className="mt-4 font-medium">{s.title}</h3>
                <p className="mx-auto mt-1.5 max-w-60 text-muted-foreground">{s.text}</p>
              </li>
            ))}
          </ol>
        </Reveal>
      </div>
    </section>
  );
}
