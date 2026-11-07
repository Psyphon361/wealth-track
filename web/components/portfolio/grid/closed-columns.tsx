import type { ReactNode } from "react";
import { createColumnHelper } from "@tanstack/react-table";
import { Badge } from "@/components/ui/badge";
import { closedOnDate, closedStatus, realisedGain, receivedAmount } from "@/lib/closed";
import { formatDate, formatINR } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { HoldingRow } from "@/lib/types";
import type { gridFeatures } from "./features";
import { ColumnHeader } from "./column-header";
import { gainTone } from "./gain-cell";
import type { GridColumn } from "./types";

/** Active-tab columns that mean nothing for a closed holding (its value is no longer held). */
const DROPPED = new Set(["current_value", "gain", "gain_pct", "status"]);

const headCls =
  "text-[11px] font-medium tracking-wider text-muted-foreground uppercase";

const dash = <span className="text-muted-foreground">—</span>;

/**
 * The Closed tab's columns: the config's own columns, minus current value, gain and the
 * generic status, plus Status, Closed On, Received and Realised Gain before the actions.
 */
export function withClosedColumns<TRow extends HoldingRow>(
  columns: GridColumn<TRow>[],
): GridColumn<TRow>[] {
  const helper = createColumnHelper<typeof gridFeatures, TRow>();

  const display = (
    id: string,
    title: string,
    render: (row: TRow) => ReactNode,
  ): GridColumn<TRow> =>
    helper.display({
      id,
      enableSorting: false,
      enableHiding: false,
      header: () => <div className={headCls}>{title}</div>,
      cell: ({ row }) => render(row.original),
    });

  /** A column sorted by the API under its own id (a header click sends sort=<id>). */
  const sortable = (
    id: string,
    title: string,
    get: (row: TRow) => number | string | null,
    render: (row: TRow) => ReactNode,
  ): GridColumn<TRow> =>
    helper.accessor(get, {
      id,
      enableHiding: false,
      header: ({ column, table }) => (
        <ColumnHeader column={column} table={table} title={title} />
      ),
      cell: ({ row }) => render(row.original),
    });

  const extra: GridColumn<TRow>[] = [
    display("closed_status", "Status", (r) => {
      const s = closedStatus(r);
      return s.attention ? (
        <Badge
          variant="outline"
          className="border-foreground/40 font-normal text-foreground"
        >
          {s.label}
        </Badge>
      ) : (
        <Badge
          variant="secondary"
          className="font-normal text-muted-foreground"
        >
          {s.label}
        </Badge>
      );
    }),
    sortable(
      "closed_on",
      "Closed On",
      closedOnDate,
      (r) => {
        const d = closedOnDate(r);
        return d ? (
          <span className="num whitespace-nowrap">{formatDate(d)}</span>
        ) : (
          dash
        );
      },
    ),
    sortable("received", "Received", receivedAmount, (r) => {
      const v = receivedAmount(r);
      return v == null ? (
        dash
      ) : (
        <span className="num whitespace-nowrap">{formatINR(v)}</span>
      );
    }),
    sortable("realised_gain", "Realised Gain", realisedGain, (r) => {
      const v = realisedGain(r);
      return v == null ? (
        dash
      ) : (
        <span className={cn("num whitespace-nowrap", gainTone(v))}>
          {v > 0 ? "+" : ""}
          {formatINR(v)}
        </span>
      );
    }),
  ];

  const kept = columns.filter((c) => !(c.id && DROPPED.has(c.id)));
  const actionsAt = kept.findIndex((c) => c.id === "actions");
  if (actionsAt === -1) return [...kept, ...extra];
  return [...kept.slice(0, actionsAt), ...extra, ...kept.slice(actionsAt)];
}
