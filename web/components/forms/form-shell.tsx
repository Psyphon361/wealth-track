import { Button } from "@/components/ui/button";
import { FieldGroup } from "@/components/ui/field";

export function FormShell({
  onSubmit,
  saving,
  editing,
  children,
}: {
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  saving: boolean;
  editing: boolean;
  children: React.ReactNode;
}) {
  return (
    <form onSubmit={onSubmit} noValidate>
      <FieldGroup>
        <div className="grid gap-5 sm:grid-cols-2">{children}</div>
        <div>
          <Button type="submit" disabled={saving}>
            {saving ? "Saving…" : editing ? "Save changes" : "Add asset"}
          </Button>
        </div>
      </FieldGroup>
    </form>
  );
}
