"use client";

import { useRef, useState } from "react";
import { UploadIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiPostForm } from "@/lib/api";
import { notify } from "@/lib/notify";
import type { CasPreview } from "@/lib/types";

const MAX_BYTES = 4 * 1024 * 1024;

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function CasUploadStep({
  onPreview,
}: {
  onPreview: (preview: CasPreview) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function pickFile(f: File | null) {
    setFile(f);
    setFileError(null);
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    let ok = true;
    if (!file) {
      setFileError("Choose your CAS PDF.");
      ok = false;
    } else if (file.size > MAX_BYTES) {
      setFileError("The file must be 4 MB or smaller.");
      ok = false;
    }
    if (!password.trim()) {
      setPasswordError("Enter the statement password.");
      ok = false;
    }
    if (!ok || !file) return;

    const form = new FormData();
    form.append("file", file);
    form.append("password", password);
    setLoading(true);
    try {
      const preview = await apiPostForm<CasPreview>(
        "/import/cas/preview",
        form,
      );
      onPreview(preview);
    } catch (err) {
      notify.error(err);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Statement PDF</Label>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={loading}
          data-invalid={fileError ? "true" : undefined}
          className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-dashed border-input px-4 py-8 text-sm text-muted-foreground transition-colors outline-none hover:bg-muted/40 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 data-[invalid=true]:border-destructive"
        >
          <UploadIcon className="size-5" />
          {file ? (
            <span className="text-foreground">
              {file.name} <span className="num text-muted-foreground">({formatSize(file.size)})</span>
            </span>
          ) : (
            <span>Choose your CAS PDF</span>
          )}
        </button>
        {fileError ? (
          <p className="text-xs text-destructive">{fileError}</p>
        ) : null}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="cas-password" className="text-xs text-muted-foreground">
          Password
        </Label>
        <Input
          id="cas-password"
          type="password"
          autoComplete="off"
          value={password}
          disabled={loading}
          aria-invalid={!!passwordError}
          onChange={(e) => {
            setPassword(e.target.value);
            setPasswordError(null);
          }}
        />
        {passwordError ? (
          <p className="text-xs text-destructive">{passwordError}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Usually your PAN in capitals
          </p>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Download your CAS from MF Central or CAMS. The file and password
        aren&apos;t stored.
      </p>
      <div className="flex justify-end">
        <Button type="submit" disabled={loading}>
          {loading ? "Reading…" : "Read statement"}
        </Button>
      </div>
    </form>
  );
}
