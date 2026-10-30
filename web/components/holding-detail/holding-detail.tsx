"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { useBreadcrumbLabel } from "@/components/breadcrumb-label";
import { DeleteDialog, type DeleteTarget } from "@/components/portfolio/delete-dialog";
import { EditDialog } from "@/components/portfolio/edit-dialog";
import { bondConfig } from "@/components/portfolio/grid/configs/bond";
import { fdConfig } from "@/components/portfolio/grid/configs/fd";
import { mfConfig } from "@/components/portfolio/grid/configs/mf";
import { rdConfig } from "@/components/portfolio/grid/configs/rd";
import { StatusBadge } from "@/components/portfolio/grid/configs/shared";
import { stockConfig } from "@/components/portfolio/grid/configs/stock";
import type { GridConfig } from "@/components/portfolio/grid/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { apiDelete } from "@/lib/api";
import { getAssetEntry } from "@/lib/asset-catalog";
import { notify } from "@/lib/notify";
import { ASSET_TYPE_LABELS, type AssetType, type HoldingRow } from "@/lib/types";
import { KpiStrip } from "./kpi-strip";
import { NotesSection, Section } from "./sections";
import { TenureBar } from "./tenure-bar";
import { useHoldingDetail } from "./use-holding-detail";

export function HoldingDetailSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-4 w-32" />
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 rounded-lg" />
        <div className="space-y-1.5">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-3.5 w-40" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[72px] rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-60 rounded-xl" />
    </div>
  );
}

function TypedDetail<TRow extends HoldingRow>({
  config,
  id,
}: {
  config: GridConfig<TRow>;
  id: number;
}) {
  const router = useRouter();
  const { data, error, refetch, retry } = useHoldingDetail<TRow>(config.type, id);
  const [editing, setEditing] = useState<TRow | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const entry = getAssetEntry(config.type);
  const backHref = `/portfolio/${config.type}`;
  useBreadcrumbLabel(data ? config.rowName(data.item) : null);

  const back = (
    <Link
      href={backHref}
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      {ASSET_TYPE_LABELS[config.type]}
    </Link>
  );

  if (error) {
    return (
      <div className="space-y-4">
        {back}
        <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 p-4">
          <div>
            <p className="text-sm font-medium text-destructive">{error.message}</p>
            {error.description ? (
              <p className="text-sm text-muted-foreground">{error.description}</p>
            ) : null}
          </div>
          <Button variant="outline" onClick={retry}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (!data) return <HoldingDetailSkeleton />;

  const { item, master } = data;
  const { detail } = config;
  const name = config.rowName(item);
  const subtitle = detail.subtitle(item);
  const tenure = detail.tenure?.(item) ?? null;
  const hasStatus = config.type === "fd" || config.type === "rd" || config.type === "bond";

  function handleDelete(target: DeleteTarget) {
    setDeleting(null);
    apiDelete(`/assets/${target.type}/${target.id}`)
      .then((res) => {
        notify.success(res);
        router.push(backHref);
      })
      .catch((err: unknown) => notify.error(err));
  }

  return (
    <div className="space-y-4">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {entry ? <AssetTypeIcon icon={entry.icon} /> : null}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-medium break-words">{name}</h2>
              {hasStatus ? <StatusBadge status={item.status} /> : null}
            </div>
            {subtitle ? (
              <p className="text-xs text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setEditing(item)}>
            <Pencil aria-hidden />
            Edit
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => setDeleting({ type: config.type, id: item.id, name })}
          >
            <Trash2 aria-hidden />
            Delete
          </Button>
        </div>
      </div>

      <KpiStrip item={item} fourth={detail.kpi(item)} />
      {tenure ? <TenureBar start={tenure.start} end={tenure.end} /> : null}

      <Section title="Holding" fields={detail.holding(item)} />
      {master ? (
        <Section title="Instrument" fields={detail.instrument(master, item)} />
      ) : null}
      {item.notes ? <NotesSection notes={item.notes} /> : null}

      <EditDialog
        config={config}
        row={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          refetch();
        }}
      />
      <DeleteDialog
        target={deleting}
        onClose={() => setDeleting(null)}
        onConfirm={handleDelete}
      />
    </div>
  );
}

export function HoldingDetail({ type, id }: { type: AssetType; id: number }) {
  switch (type) {
    case "fd":
      return <TypedDetail config={fdConfig} id={id} />;
    case "rd":
      return <TypedDetail config={rdConfig} id={id} />;
    case "stock":
      return <TypedDetail config={stockConfig} id={id} />;
    case "bond":
      return <TypedDetail config={bondConfig} id={id} />;
    case "mf":
      return <TypedDetail config={mfConfig} id={id} />;
  }
}
