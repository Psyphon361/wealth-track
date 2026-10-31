"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiPost } from "@/lib/api";
import { formatDate, formatINR } from "@/lib/format";
import { notify } from "@/lib/notify";
import type {
  CasCommitResult,
  CasCommitRow,
  CasPreview,
  CasPreviewRow,
} from "@/lib/types";

type RowAction = "update" | "create";

const ACTION_OPTIONS = [
  { value: "update", label: "Update existing" },
  { value: "create", label: "Add as new" },
];

const PLAN_LABELS = { direct: "Direct", regular: "Regular" } as const;
const OPTION_LABELS = {
  growth: "Growth",
  idcw: "IDCW",
  bonus: "Bonus",
  other: "Other",
} as const;

const units3 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});
const nav4 = new Intl.NumberFormat("en-IN", {
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

function subLine(r: CasPreviewRow): string {
  const parts = [r.amc];
  if (r.plan) parts.push(PLAN_LABELS[r.plan]);
  if (r.option) parts.push(OPTION_LABELS[r.option]);
  const n = r.folios.length;
  if (n > 0) parts.push(`${n} folio${n === 1 ? "" : "s"}`);
  return parts.filter(Boolean).join(" · ");
}

export function CasPreviewStep({
  preview,
  onBack,
  onImported,
}: {
  preview: CasPreview;
  onBack: () => void;
  onImported: (result: CasCommitResult) => void;
}) {
  const { rows } = preview;
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(rows.filter((r) => r.importable).map((r) => r.key)),
  );
  const [actions, setActions] = useState<Record<string, RowAction>>({});
  const [importing, setImporting] = useState(false);

  const importable = rows.filter((r) => r.importable);
  const checkedCount = importable.filter((r) => selected.has(r.key)).length;
  const allChecked = importable.length > 0 && checkedCount === importable.length;
  const someChecked = checkedCount > 0 && !allChecked;

  function toggle(key: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleAll(on: boolean) {
    setSelected(on ? new Set(importable.map((r) => r.key)) : new Set());
  }

  function actionFor(r: CasPreviewRow): RowAction {
    if (r.existing.length !== 1) return "create";
    return actions[r.key] ?? "update";
  }

  async function submit() {
    const body: CasCommitRow[] = importable
      .filter((r) => selected.has(r.key))
      .map((r) => {
        const action = actionFor(r);
        return {
          action,
          holding_id: action === "update" ? r.existing[0].id : null,
          scheme_code: r.scheme_code,
          scheme_name: r.scheme_name,
          category: r.category,
          units: r.units,
          avg_nav: r.avg_nav,
          invested_amount: r.invested_amount,
          purchase_date: r.purchase_date,
          transactions: r.transactions,
        };
      });
    setImporting(true);
    try {
      const result = await apiPost<CasCommitResult>("/import/cas/commit", {
        rows: body,
      });
      notify.success(result);
      onImported(result);
    } catch (err) {
      notify.error(err);
      setImporting(false);
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
        <p>
          Statement period{" "}
          <span className="num text-foreground">
            {formatDate(preview.statement_from)} to{" "}
            {formatDate(preview.statement_to)}
          </span>
        </p>
        {preview.hidden_zero > 0 ? (
          <p>
            {preview.hidden_zero} fund{preview.hidden_zero === 1 ? "" : "s"}{" "}
            with zero units hidden
          </p>
        ) : null}
      </div>

      <div className="min-w-0 overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <Checkbox
                  checked={allChecked}
                  indeterminate={someChecked}
                  disabled={importable.length === 0 || importing}
                  onCheckedChange={(v) => toggleAll(v)}
                  aria-label="Select all funds"
                />
              </TableHead>
              <TableHead>Fund</TableHead>
              <TableHead className="text-right">Units</TableHead>
              <TableHead className="text-right">Invested</TableHead>
              <TableHead className="text-right">Avg NAV</TableHead>
              <TableHead>Purchase date</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const action = actionFor(r);
              return (
                <TableRow
                  key={r.key}
                  className={r.importable ? undefined : "opacity-60"}
                >
                  <TableCell>
                    <Checkbox
                      checked={r.importable && selected.has(r.key)}
                      disabled={!r.importable || importing}
                      onCheckedChange={(v) => toggle(r.key, v)}
                      aria-label={`Select ${r.scheme_name}`}
                    />
                  </TableCell>
                  <TableCell className="min-w-56 whitespace-normal">
                    <div className="font-medium">{r.scheme_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {subLine(r)}
                    </div>
                    {r.issue ? (
                      <div className="text-xs text-destructive">{r.issue}</div>
                    ) : null}
                  </TableCell>
                  <TableCell className="num text-right">
                    {units3.format(r.units)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {formatINR(r.invested_amount)}
                  </TableCell>
                  <TableCell className="num text-right">
                    {nav4.format(r.avg_nav)}
                  </TableCell>
                  <TableCell className="num">
                    {r.purchase_date ? formatDate(r.purchase_date) : "—"}
                  </TableCell>
                  <TableCell className="whitespace-normal">
                    {r.existing.length === 0 ? (
                      <Badge variant="secondary">New</Badge>
                    ) : (
                      <div className="flex flex-col items-start gap-1">
                        <Badge variant="outline">In portfolio</Badge>
                        {r.existing.length === 1 ? (
                          <>
                            <Select
                              items={ACTION_OPTIONS}
                              value={action}
                              disabled={!r.importable || importing}
                              onValueChange={(v) =>
                                setActions((prev) => ({
                                  ...prev,
                                  [r.key]: (v as RowAction) ?? "update",
                                }))
                              }
                            >
                              <SelectTrigger size="sm" className="w-36">
                                <SelectValue />
                              </SelectTrigger>
                              <SelectContent>
                                {ACTION_OPTIONS.map((o) => (
                                  <SelectItem key={o.value} value={o.value}>
                                    {o.label}
                                  </SelectItem>
                                ))}
                              </SelectContent>
                            </Select>
                            <span className="num text-xs text-muted-foreground">
                              {units3.format(r.existing[0].units)} →{" "}
                              {units3.format(r.units)} units
                            </span>
                          </>
                        ) : (
                          <span className="text-xs text-muted-foreground">
                            Matches {r.existing.length} holdings
                          </span>
                        )}
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <Button
          type="button"
          variant="outline"
          onClick={onBack}
          disabled={importing}
        >
          Back
        </Button>
        <Button
          type="button"
          onClick={submit}
          disabled={checkedCount === 0 || importing}
        >
          {importing
            ? "Importing…"
            : `Import ${checkedCount} fund${checkedCount === 1 ? "" : "s"}`}
        </Button>
      </div>
    </div>
  );
}
