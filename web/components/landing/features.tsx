import { Calculator, FileUp, IndianRupee, Layers, LineChart, RefreshCw } from "lucide-react";
import { Reveal } from "./reveal";

const features = [
  { icon: Layers, title: "Five asset classes, one view", text: "Fixed deposits, recurring deposits, stocks, bonds and mutual funds on a single dashboard." },
  { icon: RefreshCw, title: "Prices updated nightly", text: "NSE/BSE closing prices and AMFI NAVs keep every holding valued without any effort." },
  { icon: FileUp, title: "Import your CAS", text: "Upload your MF Central or CAMS statement — every fund, folio and SIP in one go." },
  { icon: LineChart, title: "True XIRR", text: "Calculated from your actual SIP history, not a guess." },
  { icon: Calculator, title: "FD & RD maths done right", text: "Maturity value, interest received and compounding handled for you." },
  { icon: IndianRupee, title: "Indian formatting everywhere", text: "₹1,00,000, not 100,000. Lakhs and crores the way you read them." },
];

export function Features() {
  return (
    <section className="px-4 py-20">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-xl text-center">
          <h2 className="text-3xl font-semibold tracking-tight">Everything you hold, understood</h2>
          <p className="mt-3 text-muted-foreground">Quiet, accurate and made for how Indians invest.</p>
        </Reveal>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f, i) => (
            <Reveal key={f.title} delay={(i % 3) * 80}>
              <div className="h-full rounded-xl border border-border bg-card/60 p-5 transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/40">
                <span className="flex size-9 items-center justify-center rounded-lg bg-primary/15 text-primary">
                  <f.icon className="size-4.5" />
                </span>
                <h3 className="mt-4 font-medium">{f.title}</h3>
                <p className="mt-1.5 text-muted-foreground">{f.text}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}
