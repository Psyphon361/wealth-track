import { cn } from "@/lib/utils";

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const rupee = (n: number) => `₹${inr.format(n)}`;

const kpis = [
  { label: "Net worth", value: rupee(2486310), sub: "Across 5 asset types" },
  { label: "Invested", value: rupee(2012500), sub: "Total cost" },
  { label: "Gain", value: `+${rupee(473810)}`, sub: "+23.54%", gain: true },
  { label: "XIRR", value: "14.2%", sub: "From your SIP history", gain: true },
];

const rows = [
  { type: "Fixed deposits", invested: 450000, current: 492380 },
  { type: "Recurring deposits", invested: 120000, current: 126940 },
  { type: "Stocks", invested: 520000, current: 658200 },
  { type: "Bonds", invested: 210000, current: 224870 },
  { type: "Mutual funds", invested: 712500, current: 983920 },
];

export function ProductPreview() {
  return (
    <div className="mx-auto mt-14 max-w-4xl [perspective:1400px]">
      <div
        className={cn(
          "overflow-hidden rounded-2xl border border-border bg-card/60 backdrop-blur-xl",
          "shadow-[0_0_80px_-10px_oklch(0.696_0.15_163/0.3)]",
          "transition-transform duration-700 ease-out [transform:rotateX(10deg)] hover:[transform:rotateX(0deg)] md:[transform:rotateX(6deg)]",
        )}
      >
        <div className="flex items-center gap-1.5 border-b border-border px-4 py-2.5">
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
          <span className="size-2.5 rounded-full bg-muted-foreground/30" />
          <span className="ml-3 text-xs text-muted-foreground">Dashboard</span>
        </div>
        <div className="space-y-4 p-4 sm:p-5">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {kpis.map((k) => (
              <div key={k.label} className="rounded-xl border border-border bg-background/40 p-3">
                <div className="text-xs text-muted-foreground">{k.label}</div>
                <div className={cn("num mt-1 text-base font-semibold sm:text-lg", k.gain && "text-gain")}>
                  {k.value}
                </div>
                <div className={cn("num mt-0.5 truncate text-xs", k.gain && k.sub.startsWith("+") ? "text-gain" : "text-muted-foreground")}>
                  {k.sub}
                </div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-border bg-background/40">
            <div className="border-b border-border px-3 py-2 text-xs font-medium">Holdings by type</div>
            <table className="w-full text-left text-xs sm:text-sm">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-normal">Type</th>
                  <th className="px-3 py-2 text-right font-normal">Invested</th>
                  <th className="hidden px-3 py-2 text-right font-normal sm:table-cell">Current</th>
                  <th className="px-3 py-2 text-right font-normal">Gain</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const g = r.current - r.invested;
                  return (
                    <tr key={r.type} className="border-t border-border">
                      <td className="px-3 py-2">{r.type}</td>
                      <td className="num px-3 py-2 text-right">{rupee(r.invested)}</td>
                      <td className="num hidden px-3 py-2 text-right sm:table-cell">{rupee(r.current)}</td>
                      <td className="num px-3 py-2 text-right text-gain">
                        +{((g / r.invested) * 100).toFixed(1)}%
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
