import { excludedText, ratesText } from "@/lib/returns";
import type { ReferenceRate, ReturnsExcluded as Excluded } from "@/lib/types";

export function ReturnsExcluded({ excluded, rates }: { excluded: Excluded; rates: ReferenceRate[] }) {
  const text = excludedText(excluded);
  const rateLine = ratesText(rates);
  if (!text && !rateLine) return null;

  return (
    <div className="space-y-0.5 text-xs text-muted-foreground">
      {text && <p>{text}</p>}
      {rateLine && <p className="num">{rateLine}</p>}
    </div>
  );
}
