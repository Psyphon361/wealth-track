"use client";

import { useState } from "react";
import type { CasCommitResult, CasPreview } from "@/lib/types";
import { CasPreviewStep } from "./preview-step";
import { CasUploadStep } from "./upload-step";

export function CasImport({
  onImported,
}: {
  onImported: (result: CasCommitResult) => void;
}) {
  const [preview, setPreview] = useState<CasPreview | null>(null);

  if (!preview) return <CasUploadStep onPreview={setPreview} />;
  return (
    <CasPreviewStep
      preview={preview}
      onBack={() => setPreview(null)}
      onImported={onImported}
    />
  );
}
