import { Card } from "@/components/ui/card";
import type { DetailField } from "@/components/portfolio/grid/types";
import { cn } from "@/lib/utils";

export const LABEL =
  "text-[11px] font-medium tracking-wider text-muted-foreground uppercase";

export function Section({
  title,
  fields,
}: {
  title: string;
  fields: DetailField[];
}) {
  return (
    <Card size="sm" className="gap-3 px-4">
      <h3 className={LABEL}>{title}</h3>
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {fields.map((f) => (
          <div key={f.label} className="min-w-0">
            <dt className="text-xs text-muted-foreground">{f.label}</dt>
            <dd className={cn("text-sm break-words", f.figure && "num")}>
              {f.value ? f.value : <span className="text-muted-foreground">—</span>}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

export function NotesSection({ notes }: { notes: string }) {
  return (
    <Card size="sm" className="gap-3 px-4">
      <h3 className={LABEL}>Notes</h3>
      <p className="text-sm break-words whitespace-pre-wrap">{notes}</p>
    </Card>
  );
}
