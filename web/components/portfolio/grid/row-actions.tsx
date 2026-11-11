"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import {
  CircleCheck,
  Eye,
  HandCoins,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { UpdateValueDialog } from "@/components/portfolio/update-value-dialog";
import { canUpdateValue, updateValueLabel } from "@/lib/update-value";
import { BuyDialog } from "@/components/buy/buy-dialog";
import { SellDialog } from "@/components/exits/sell-dialog";
import { SettleDialog } from "@/components/exits/settle-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { deleteBlockedReason, isDeleteBlocked } from "@/lib/delete-guard";
import { canBuy } from "@/lib/buy";
import { canEdit } from "@/lib/edit-guards";
import { canSell, canSettle } from "@/lib/exits";
import type { AssetType, HoldingRow, MutualFundItem } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Flip once the /portfolio/{type}/{id} details page exists. */
const DETAILS_ENABLED = true;

interface MenuEntry {
  key: string;
  label: string;
  icon: ReactNode;
  destructive?: boolean;
  separatorBefore?: boolean;
  /** Set when the item is disabled; shown in a tooltip. */
  blockedReason?: string;
  run: () => void;
}

export function RowActions({
  type,
  id,
  name,
  row,
  onEdit,
  onDelete,
}: {
  type: AssetType;
  id: number;
  name: string;
  row: HoldingRow;
  onEdit: () => void;
  onDelete: () => void;
}) {
  // Sell and Settle open their own dialogs, so the grid needs no handlers for them.
  const [dialog, setDialog] = useState<"sell" | "settle" | "update" | "buy" | null>(null);
  const entries: MenuEntry[] = [];
  if (canBuy(type, row)) {
    entries.push({
      key: "buy",
      label: "Buy More",
      icon: <Plus />,
      run: () => setDialog("buy"),
    });
  }
  if (canSell(type, row)) {
    entries.push({
      key: "sell",
      label: "Sell",
      icon: <HandCoins />,
      run: () => setDialog("sell"),
    });
  }
  if (canSettle(type, row)) {
    entries.push({
      key: "settle",
      label: "Settle",
      icon: <CircleCheck />,
      run: () => setDialog("settle"),
    });
  }
  // Quick refresh of the balance, value or units (not on closed holdings).
  if (canUpdateValue(type, row)) {
    entries.push({
      key: "update",
      label: updateValueLabel(type) ?? "",
      icon: <RefreshCw />,
      run: () => setDialog("update"),
    });
  }
  // Sold or settled holdings can't be edited until the exit is undone.
  if (canEdit(row)) {
    entries.push({
      key: "edit",
      label: "Edit",
      icon: <Pencil />,
      run: onEdit,
    });
  }
  // Sold or settled holdings can't be deleted until the exit is undone.
  const deleteReason = deleteBlockedReason(row);
  entries.push({
    key: "delete",
    label: "Delete",
    icon: <Trash2 />,
    destructive: true,
    separatorBefore: canEdit(row) || entries.length > 0,
    blockedReason: deleteReason?.message,
    run: () => {
      if (!isDeleteBlocked(row)) onDelete();
    },
  });

  return (
    <div className="flex items-center justify-end gap-0.5">
      {DETAILS_ENABLED ? (
        <Link
          href={`/portfolio/${type}/${id}`}
          aria-label={`View ${name}`}
          className={cn(
            buttonVariants({ variant: "ghost", size: "icon-xs" }),
            "text-muted-foreground",
          )}
        >
          <Eye />
        </Link>
      ) : (
        <Tooltip>
          <TooltipTrigger
            render={<span className="inline-flex" tabIndex={0} />}
          >
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              disabled
              aria-label={`View ${name}`}
              className="text-muted-foreground"
            >
              <Eye />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Details coming soon</TooltipContent>
        </Tooltip>
      )}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={`More actions for ${name}`}
              className="text-muted-foreground"
            />
          }
        >
          <MoreHorizontal />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          {entries.map((e) => (
            <div key={e.key} className="contents">
              {e.separatorBefore ? <DropdownMenuSeparator /> : null}
              {e.blockedReason ? (
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <DropdownMenuItem
                        variant={e.destructive ? "destructive" : "default"}
                        aria-disabled
                        closeOnClick={false}
                        className="cursor-not-allowed opacity-50"
                        onClick={() => {}}
                      />
                    }
                  >
                    {e.icon}
                    {e.label}
                  </TooltipTrigger>
                  <TooltipContent side="left">{e.blockedReason}</TooltipContent>
                </Tooltip>
              ) : (
                <DropdownMenuItem
                  variant={e.destructive ? "destructive" : "default"}
                  onClick={e.run}
                >
                  {e.icon}
                  {e.label}
                </DropdownMenuItem>
              )}
            </div>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <BuyDialog
        row={dialog === "buy" && type === "mf" ? (row as MutualFundItem) : null}
        name={name}
        onClose={() => setDialog(null)}
      />
      <SellDialog
        type={type}
        row={dialog === "sell" ? row : null}
        name={name}
        onClose={() => setDialog(null)}
      />
      <SettleDialog
        type={type}
        row={dialog === "settle" ? row : null}
        name={name}
        onClose={() => setDialog(null)}
      />
      <UpdateValueDialog
        type={type}
        row={dialog === "update" ? row : null}
        name={name}
        onClose={() => setDialog(null)}
      />
    </div>
  );
}
