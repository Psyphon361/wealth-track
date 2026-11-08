"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, apiPatch } from "@/lib/api";
import { notify } from "@/lib/notify";
import { cleanName } from "@/lib/profile";

export function EditNameDialog({
  open,
  onOpenChange,
  initialName,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialName: string | null;
  onSaved: (fullName: string | null) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        {open ? (
          <NameForm
            initialName={initialName}
            onClose={() => onOpenChange(false)}
            onSaved={onSaved}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function NameForm({
  initialName,
  onClose,
  onSaved,
}: {
  initialName: string | null;
  onClose: () => void;
  onSaved: (fullName: string | null) => void;
}) {
  const [value, setValue] = useState(initialName ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function change(next: string) {
    setValue(next);
    setError(cleanName(next).error);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving) return;
    const result = cleanName(value);
    if (result.error) {
      setError(result.error);
      return;
    }
    setSaving(true);
    try {
      const data = await apiPatch<{
        message: string;
        description: string;
        user?: { full_name?: string | null };
      }>("/me", { full_name: result.name });
      notify.success(data);
      onSaved(data.user?.full_name ?? null);
      onClose();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422 && Array.isArray(err.detail)) {
        const item = (err.detail as { loc?: unknown[]; msg?: string }[]).find(
          (d) => d.loc?.includes("full_name") && d.msg,
        );
        if (item?.msg) {
          setError(item.msg);
          return;
        }
      }
      notify.error(err);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      <DialogHeader>
        <DialogTitle>Your Name</DialogTitle>
      </DialogHeader>
      <div className="space-y-1.5">
        <Label htmlFor="full-name">Full Name</Label>
        <Input
          id="full-name"
          type="text"
          name="full_name"
          value={value}
          onChange={(e) => change(e.target.value)}
          autoComplete="name"
          disabled={saving}
          aria-invalid={error ? true : undefined}
          className="text-base md:text-sm"
          autoFocus
        />
        {error ? <p className="text-xs text-destructive">{error}</p> : null}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" disabled={saving} onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? (
            <>
              <Loader2 className="animate-spin" aria-hidden />
              Saving…
            </>
          ) : (
            "Save"
          )}
        </Button>
      </DialogFooter>
    </form>
  );
}
