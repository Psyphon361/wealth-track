import type { ReactNode } from "react";
import {
  createColumnHelper,
  type HeaderContext,
} from "@tanstack/react-table";
import { Badge } from "@/components/ui/badge";
import { formatDate, formatINR, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { HoldingRow, HoldingStatus } from "@/lib/types";
import { ColumnHeader } from "../column-header";
import type { gridFeatures } from "../features";
import { GainCell, gainTone } from "../gain-cell";
import { RowActions } from "../row-actions";
import type { GridColumn, GridConfig, RowHandlers } from "../types";

export const STATUS_LABELS: Record<HoldingStatus, string> = {
  active: "Active",
  matured: "Matured",
};

const dash = <span className="text-muted-foreground">—</span>;

export function StatusBadge({ status }: { status: HoldingStatus }) {
  return status === "active" ? (
    <Badge variant="outline" className="font-normal">
      {STATUS_LABELS.active}
    </Badge>
  ) : (
    <Badge variant="secondary" className="font-normal text-muted-foreground">
      {STATUS_LABELS.matured}
    </Badge>
  );
}

/** Column builders shared by every asset-type grid. */
export function createColumnKit<TRow extends HoldingRow>(
  type: GridConfig<TRow>["type"],
  labels: Record<string, string>,
  rowName: (row: TRow) => string,
) {
  const helper = createColumnHelper<typeof gridFeatures, TRow>();

  const head = (id: string) =>
    function SortableHeader<TValue>({
      column,
      table,
    }: HeaderContext<typeof gridFeatures, TRow, TValue>) {
      return (
        <ColumnHeader
          column={column}
          table={table}
          title={labels[id]}
        />
      );
    };

  /** Primary column: bold title with an optional muted sub-line. Cannot be hidden. */
  const primary = (
    id: string,
    get: (row: TRow) => string,
    sub: (row: TRow) => string | null | undefined,
  ): GridColumn<TRow> =>
    helper.accessor(get, {
      id,
      header: head(id),
      enableHiding: false,
      cell: ({ row }) => {
        const line = sub(row.original);
        return (
          <div className="min-w-32 leading-tight">
            <div className="font-medium">{get(row.original)}</div>
            {line ? (
              <div className="text-[11px] text-muted-foreground">{line}</div>
            ) : null}
          </div>
        );
      },
    });

  const text = (
    id: string,
    get: (row: TRow) => string | null | undefined,
    render?: (row: TRow) => ReactNode,
  ): GridColumn<TRow> =>
    helper.accessor((row) => get(row) ?? "", {
      id,
      header: head(id),
      cell: ({ row }) => {
        if (render) return render(row.original);
        const v = get(row.original);
        return v ? <span className="whitespace-nowrap">{v}</span> : dash;
      },
    });

  const money = (
    id: string,
    get: (row: TRow) => number,
  ): GridColumn<TRow> =>
    helper.accessor(get, {
      id,
      header: head(id),
      cell: ({ row }) => (
        <span className="num whitespace-nowrap">
          {formatINR(get(row.original))}
        </span>
      ),
    });

  const number = (
    id: string,
    get: (row: TRow) => number,
    format: (n: number) => string,
  ): GridColumn<TRow> =>
    helper.accessor(get, {
      id,
      header: head(id),
      cell: ({ row }) => (
        <span className="num whitespace-nowrap">{format(get(row.original))}</span>
      ),
    });

  const date = (
    id: string,
    get: (row: TRow) => string | null | undefined,
  ): GridColumn<TRow> =>
    helper.accessor((row) => get(row) ?? "", {
      id,
      header: head(id),
      cell: ({ row }) => {
        const v = get(row.original);
        return v ? (
          <span className="num whitespace-nowrap">{formatDate(v)}</span>
        ) : (
          dash
        );
      },
    });

  /** Non-sortable column with a custom cell. */
  const display = (
    id: string,
    render: (row: TRow) => ReactNode,
  ): GridColumn<TRow> =>
    helper.display({
      id,
      enableSorting: false,
      header: () => (
        <div
          className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase"
        >
          {labels[id]}
        </div>
      ),
      cell: ({ row }) => render(row.original),
    });

  const percent = (
    id: string,
    get: (row: TRow) => number,
  ): GridColumn<TRow> => number(id, get, formatPct);

  const gain = (): GridColumn<TRow> =>
    helper.accessor((row) => row.gain, {
      id: "gain",
      header: head("gain"),
      cell: ({ row }) => (
        <GainCell
          gain={row.original.gain}
          pct={row.original.gain_pct}
          showPct={false}
        />
      ),
    });

  const gainPct = (): GridColumn<TRow> =>
    helper.accessor((row) => row.gain_pct, {
      id: "gain_pct",
      header: head("gain_pct"),
      cell: ({ row }) => {
        const { gain: g, gain_pct } = row.original;
        return (
          <span className={cn("num whitespace-nowrap", gainTone(g))}>
            {g > 0 ? "+" : ""}
            {formatPct(gain_pct)}
          </span>
        );
      },
    });

  const status = (): GridColumn<TRow> =>
    helper.accessor((row) => row.status, {
      id: "status",
      header: head("status"),
      cell: ({ row }) => <StatusBadge status={row.original.status} />,
    });

  const actions = (handlers: RowHandlers<TRow>): GridColumn<TRow> =>
    helper.display({
      id: "actions",
      enableSorting: false,
      enableHiding: false,
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <RowActions
          type={type}
          id={row.original.id}
          name={rowName(row.original)}
          onEdit={() => handlers.onEdit(row.original)}
          onDelete={() => handlers.onDelete(row.original)}
        />
      ),
    });

  return {
    primary,
    text,
    money,
    number,
    date,
    display,
    percent,
    gain,
    gainPct,
    status,
    actions,
  };
}
