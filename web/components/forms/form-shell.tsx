import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export function FormShell({
  onSubmit,
  saving,
  editing,
  onCancel,
  children,
}: {
  onSubmit: React.FormEventHandler<HTMLFormElement>;
  saving: boolean;
  editing: boolean;
  onCancel?: () => void;
  children: React.ReactNode;
}) {
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-8">
      <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">{children}</div>
      <div className="flex items-center justify-end gap-2 border-t pt-5">
        {onCancel ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </Button>
        ) : null}
        <Button type="submit" disabled={saving}>
          {saving ? <Loader2 className="animate-spin" /> : null}
          {saving ? "Saving" : editing ? "Save changes" : "Add asset"}
        </Button>
      </div>
    </form>
  );
}
