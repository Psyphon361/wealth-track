import Link from "next/link";
import {
  createColumnHelper,
  type ColumnDef,
  type HeaderContext,
} from "@tanstack/react-table";
import { ColumnHeader } from "@/components/portfolio/grid/column-header";
import type { gridFeatures } from "@/components/portfolio/grid/features";
import { formatDate, formatINRWhole } from "@/lib/format";
import {
  countdownText,
  isNextSkipped,
  ordinal,
  platformLabel,
  shortDate,
} from "@/lib/sip";
import type { Sip } from "@/lib/types";
import { SipBadge } from "./sip-badge";
import { SipActions } from "./sip-actions";

type Features = typeof gridFeatures;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SipColumn = ColumnDef<Features, Sip, any>;

/** Header and Columns-menu text by column id. */
export const sipColumnLabels: Record<string, string> = {
  fund_name: "Fund",
  status: "Status",
  amount: "Monthly amount",
  day_of_month: "SIP date",
  next_date: "Next instalment",
  instalments_added: "Instalments",
  invested_via_sip: "Invested via SIP",
};

const helper = createColumnHelper<Features, Sip>();

const dash = <span className="text-muted-foreground">—</span>;

function sortableHeader(id: string) {
  return function SortableHeader<TValue>({
    column,
    table,
  }: HeaderContext<Features, Sip, TValue>) {
    return (
      <ColumnHeader column={column} table={table} title={sipColumnLabels[id]} />
    );
  };
}

function NextCell({ sip, today }: { sip: Sip; today: string }) {
  if (sip.status !== "active" || !sip.next_date) return dash;
  if (isNextSkipped(sip)) {
    return (
      <span className="num whitespace-nowrap text-amber-300">
        Skipping {shortDate(sip.next_date)}
      </span>
    );
  }
  return (
    <div className="leading-tight">
      <div className="num whitespace-nowrap">{formatDate(sip.next_date)}</div>
      <div className="text-[11px] whitespace-nowrap text-muted-foreground">
        {countdownText(sip.next_date, today)}
      </div>
    </div>
  );
}

/** Columns of the SIPs grid; same cell styles as the holdings grids. */
export function createSipColumns({
  today,
  onChanged,
}: {
  today: string;
  onChanged: () => void;
}): SipColumn[] {
  return [
    helper.accessor((s) => s.fund_name, {
      id: "fund_name",
      header: sortableHeader("fund_name"),
      enableHiding: false,
      cell: ({ row }) => {
        const s = row.original;
        const platform = platformLabel(s.platform);
        return (
          <div className="min-w-32 leading-tight">
            <div className="font-medium">
              {s.mutual_fund_id !== null ? (
                <Link
                  href={`/portfolio/mf/${s.mutual_fund_id}`}
                  className="underline-offset-3 hover:underline"
                >
                  {s.fund_name}
                </Link>
              ) : (
                s.fund_name
              )}
            </div>
            {platform ? (
              <div className="text-[11px] text-muted-foreground">{platform}</div>
            ) : null}
          </div>
        );
      },
    }),
    helper.accessor((s) => s.status, {
      id: "status",
      header: sortableHeader("status"),
      cell: ({ row }) => <SipBadge status={row.original.status} />,
    }),
    helper.accessor((s) => s.amount, {
      id: "amount",
      header: sortableHeader("amount"),
      cell: ({ row }) => (
        <span className="num whitespace-nowrap">
          {formatINRWhole(row.original.amount)}
        </span>
      ),
    }),
    helper.accessor((s) => s.day_of_month, {
      id: "day_of_month",
      header: sortableHeader("day_of_month"),
      cell: ({ row }) => (
        <span className="num whitespace-nowrap">
          {ordinal(row.original.day_of_month)}
        </span>
      ),
    }),
    helper.accessor((s) => s.next_date ?? "", {
      id: "next_date",
      header: sortableHeader("next_date"),
      cell: ({ row }) => <NextCell sip={row.original} today={today} />,
    }),
    helper.accessor((s) => s.instalments_added, {
      id: "instalments_added",
      header: sortableHeader("instalments_added"),
      cell: ({ row }) =>
        row.original.instalments_added === 0 ? (
          dash
        ) : (
          <span className="num whitespace-nowrap">
            {row.original.instalments_added}
          </span>
        ),
    }),
    helper.accessor((s) => s.invested_via_sip, {
      id: "invested_via_sip",
      header: sortableHeader("invested_via_sip"),
      cell: ({ row }) =>
        row.original.invested_via_sip === 0 ? (
          dash
        ) : (
          <span className="num whitespace-nowrap">
            {formatINRWhole(row.original.invested_via_sip)}
          </span>
        ),
    }),
    helper.display({
      id: "actions",
      enableSorting: false,
      enableHiding: false,
      header: () => <span className="sr-only">Actions</span>,
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-0.5">
          <SipActions sip={row.original} onChanged={onChanged} />
        </div>
      ),
    }),
  ];
}
