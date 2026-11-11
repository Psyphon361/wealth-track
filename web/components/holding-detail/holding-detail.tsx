"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft, HandCoins, Pencil, Plus, RefreshCw, Trash2 } from "lucide-react";
import { BuyDialog } from "@/components/buy/buy-dialog";
import { canBuy } from "@/lib/buy";
import { StalePill } from "@/components/portfolio/stale-pill";
import { UpdateValueDialog } from "@/components/portfolio/update-value-dialog";
import { STALE_LINE, canUpdateValue, updateValueLabel } from "@/lib/update-value";
import { BondSchedule } from "@/components/analytics/bond-schedule";
import { AssetTypeIcon } from "@/components/asset-type-icon";
import { useBreadcrumbLabel } from "@/components/breadcrumb-label";
import { SellDialog } from "@/components/exits/sell-dialog";
import { SettleDialog } from "@/components/exits/settle-dialog";
import { DeleteDialog, type DeleteTarget } from "@/components/portfolio/delete-dialog";
import { EditDialog } from "@/components/portfolio/edit-dialog";
import { bondConfig } from "@/components/portfolio/grid/configs/bond";
import { cashConfig } from "@/components/portfolio/grid/configs/cash";
import { fdConfig } from "@/components/portfolio/grid/configs/fd";
import { goldConfig } from "@/components/portfolio/grid/configs/gold";
import { mfConfig } from "@/components/portfolio/grid/configs/mf";
import { npsConfig } from "@/components/portfolio/grid/configs/nps";
import { otherConfig } from "@/components/portfolio/grid/configs/other";
import { pfConfig } from "@/components/portfolio/grid/configs/pf";
import { rdConfig } from "@/components/portfolio/grid/configs/rd";
import { StatusBadge } from "@/components/portfolio/grid/configs/shared";
import { stockConfig } from "@/components/portfolio/grid/configs/stock";
import type { GridConfig } from "@/components/portfolio/grid/types";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { apiDelete } from "@/lib/api";
import { deleteBlockedReason } from "@/lib/delete-guard";
import { canEdit } from "@/lib/edit-guards";
import {
  CASH_PAID_FROM_INFO,
  canSell,
  canSettle,
  isSellableType,
  isSettleableType,
  paidFromText,
} from "@/lib/exits";
import { formatDate } from "@/lib/format";
import { markHoldingsChanged } from "@/lib/holdings-cache";
import { invalidateNetWorth } from "@/lib/networth-cache";
import { amountText } from "@/lib/sip";
import { getAssetEntry } from "@/lib/asset-catalog";
import { notify } from "@/lib/notify";
import {
  ASSET_TYPE_LABELS,
  type AssetType,
  type HoldingRow,
  type MutualFundItem,
  type OtherItem,
  type PfItem,
} from "@/lib/types";
import { ExitsSection } from "./exits-section";
import { KpiStrip } from "./kpi-strip";
import { MfSipSection } from "./mf-sip-section";
import { MfTransactions } from "./mf-transactions";
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
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { data, error, refetch, retry } = useHoldingDetail<TRow>(config.type, id);
  const [editing, setEditing] = useState<TRow | null>(null);
  const [deleting, setDeleting] = useState<DeleteTarget | null>(null);
  const [deletePending, setDeletePending] = useState(false);
  const [selling, setSelling] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [buying, setBuying] = useState(false);
  // Bumped after a buy or an undone buy so the transactions list reloads.
  const [txVersion, setTxVersion] = useState(0);
  // The dashboard links here with ?settle=1 to open the settle dialog straight away.
  const [settling, setSettling] = useState(searchParams.get("settle") === "1");
  // Bumped after a sale, settlement or undo so the exits list reloads.
  const [exitsVersion, setExitsVersion] = useState(0);
  const entry = getAssetEntry(config.type);
  const backHref = `/portfolio/${config.type}`;
  useBreadcrumbLabel(data ? config.rowName(data.item) : null);

  const back = (
    <Link
      href={backHref}
      className="inline-flex items-center gap-1 text-[13.5px] text-muted-foreground hover:text-foreground"
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
            <p className="text-[13.5px] font-medium text-destructive">{error.message}</p>
            {error.description ? (
              <p className="text-[13.5px] text-muted-foreground">{error.description}</p>
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
  const hasStatus =
    config.type === "fd" ||
    config.type === "rd" ||
    config.type === "bond" ||
    item.status === "sold";
  const sellable = canSell(config.type, item);
  const settleable = canSettle(config.type, item);
  const deleteReason = deleteBlockedReason(item);
  const paidFrom = paidFromText(item);
  const hasExits =isSellableType(config.type) || isSettleableType(config.type);

  const buyable = canBuy(config.type, item);

  function buyDone() {
    refetch();
    setTxVersion((n) => n + 1);
  }

  function exitDone() {
    refetch();
    setExitsVersion((n) => n + 1);
  }

  function closeSettle() {
    setSettling(false);
    if (searchParams.get("settle")) router.replace(pathname, { scroll: false });
  }

  function handleDelete(target: DeleteTarget) {
    setDeletePending(true);
    apiDelete(`/assets/${target.type}/${target.id}`)
      .then((res) => {
        invalidateNetWorth();
        markHoldingsChanged(target.type, !!target.paidFrom);
        notify.success(res);
        // The dialog stays pending (open) while the page navigates away.
        router.push(backHref);
      })
      .catch((err: unknown) => {
        setDeletePending(false);
        setDeleting(null);
        notify.error(err);
      });
  }

  return (
    <div className="space-y-4">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          {entry ? <AssetTypeIcon icon={entry.icon} /> : null}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-medium break-words">{name}</h2>
              {hasStatus ? <StatusBadge status={item.status} /> : null}
            </div>
            {subtitle ? (
              <p className="text-xs text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {buyable ? (
            <Button variant="outline" size="sm" onClick={() => setBuying(true)}>
              <Plus aria-hidden />
              Buy More
            </Button>
          ) : null}
          {sellable ? (
            <Button variant="outline" size="sm" onClick={() => setSelling(true)}>
              <HandCoins aria-hidden />
              Sell
            </Button>
          ) : null}
          {canUpdateValue(config.type, item) ? (
            <Button variant="outline" size="sm" onClick={() => setUpdating(true)}>
              <RefreshCw aria-hidden />
              {updateValueLabel(config.type)}
            </Button>
          ) : null}
          {canEdit(item) ? (
            <Button variant="outline" size="sm" onClick={() => setEditing(item)}>
              <Pencil aria-hidden />
              Edit
            </Button>
          ) : null}
          {deleteReason ? (
            <Tooltip>
              <TooltipTrigger
                render={<span className="inline-flex" tabIndex={0} />}
              >
                <Button
                  variant="ghost"
                  size="sm"
                  disabled
                  className="text-destructive"
                >
                  <Trash2 aria-hidden />
                  Delete
                </Button>
              </TooltipTrigger>
              <TooltipContent>{deleteReason.message}</TooltipContent>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:text-destructive"
              onClick={() => setDeleting({ type: config.type, id: item.id, name, paidFrom: !!item.paid_from })}
            >
              <Trash2 aria-hidden />
              Delete
            </Button>
          )}
        </div>
      </div>

      {settleable ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-muted/30 px-4 py-3">
          <p className="text-[13.5px]">
            Matured on {item.maturity_date ? formatDate(item.maturity_date) : "its maturity date"}
            {item.maturity_amount != null
              ? ` · ${amountText(item.maturity_amount)} paid out`
              : ""}
            . Where did the money go?
          </p>
          <Button size="sm" onClick={() => setSettling(true)}>
            Settle
          </Button>
        </div>
      ) : null}

      <KpiStrip
        item={item}
        fourth={detail.kpi(item)}
        showGain={
          config.type === "pf"
            ? (item as PfItem).contributed != null
            : config.type === "other"
              ? (item as OtherItem).invested_amount != null
              : config.type !== "cash"
        }
      />
      {tenure ? <TenureBar start={tenure.start} end={tenure.end} label={tenure.label} /> : null}

      {paidFrom ? (
        <p className="num text-[13.5px] text-muted-foreground">{paidFrom}</p>
      ) : null}
      {config.type === "cash" ? (
        <p className="text-[13.2px] text-muted-foreground">{CASH_PAID_FROM_INFO}</p>
      ) : null}
      {(item as { stale?: boolean }).stale ? (
        <p className="flex items-center gap-2 text-[13.2px] text-amber-300">
          <StalePill />
          {STALE_LINE}
        </p>
      ) : null}
      <Section title="Holding" fields={detail.holding(item)} />
      {master ? (
        <Section title="Instrument" fields={detail.instrument(master, item)} />
      ) : null}
      {config.type === "bond" ? <BondSchedule id={item.id} /> : null}
      {config.type === "mf" ? (
        <>
          <MfSipSection id={item.id} />
          <MfTransactions id={item.id} version={txVersion} onChanged={buyDone} />
        </>
      ) : null}
      {hasExits ? (
        <ExitsSection
          type={config.type}
          id={item.id}
          hasExit={item.exit != null}
          version={exitsVersion}
          onChanged={exitDone}
        />
      ) : null}
      {item.notes ? <NotesSection notes={item.notes} /> : null}

      <BuyDialog
        row={buying && buyable ? (item as unknown as MutualFundItem) : null}
        name={name}
        onClose={() => setBuying(false)}
        onDone={() => {
          setBuying(false);
          buyDone();
        }}
      />
      <SellDialog
        type={config.type}
        row={selling && sellable ? item : null}
        name={name}
        onClose={() => setSelling(false)}
        onDone={() => {
          setSelling(false);
          exitDone();
        }}
      />
      <SettleDialog
        type={config.type}
        row={settling && settleable ? item : null}
        name={name}
        onClose={closeSettle}
        onDone={() => {
          closeSettle();
          exitDone();
        }}
      />
      <UpdateValueDialog
        type={config.type}
        row={updating ? item : null}
        name={name}
        onClose={() => setUpdating(false)}
        onSaved={refetch}
      />
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
        pending={deletePending}
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
    case "gold":
      return <TypedDetail config={goldConfig} id={id} />;
    case "cash":
      return <TypedDetail config={cashConfig} id={id} />;
    case "pf":
      return <TypedDetail config={pfConfig} id={id} />;
    case "nps":
      return <TypedDetail config={npsConfig} id={id} />;
    case "other":
      return <TypedDetail config={otherConfig} id={id} />;
  }
}
