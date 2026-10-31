import { Calculator, FileUp, IndianRupee, Layers, LineChart, RefreshCw, ShieldCheck } from "lucide-react";
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
    <section className="px-4 py-12">
      <div className="mx-auto max-w-6xl">
        <Reveal className="mx-auto max-w-xl text-center">
          <h2 className="text-2xl font-semibold tracking-tight">Everything you hold, understood</h2>
        </Reveal>
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f, i) => (
            <Reveal key={f.title} delay={(i % 3) * 80}>
              <div className="h-full rounded-xl border border-border bg-card/60 p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/40">
                <div className="flex items-center gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
                    <f.icon className="size-4" />
                  </span>
                  <h3 className="font-medium">{f.title}</h3>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{f.text}</p>
              </div>
            </Reveal>
          ))}
        </div>
        <p className="mt-8 flex items-center justify-center gap-2 text-center text-xs text-muted-foreground">
          <ShieldCheck className="size-3.5 shrink-0" />
          Your CAS file and password are read in memory and never stored. Invite-only, no ads.
        </p>
      </div>
    </section>
  );
}
