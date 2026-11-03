import { excludedText } from "@/lib/returns";
import type { ReturnsExcluded as Excluded } from "@/lib/types";

export function ReturnsExcluded({ excluded }: { excluded: Excluded }) {
  const text = excludedText(excluded);
  if (!text) return null;

  return <p className="text-xs text-muted-foreground">{text}</p>;
}
