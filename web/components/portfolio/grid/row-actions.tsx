"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { Eye, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
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
import type { AssetType } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Flip once the /portfolio/{type}/{id} details page exists. */
const DETAILS_ENABLED = true;

interface MenuEntry {
  key: string;
  label: string;
  icon: ReactNode;
  destructive?: boolean;
  separatorBefore?: boolean;
  run: () => void;
}

export function RowActions({
  type,
  id,
  name,
  onEdit,
  onDelete,
}: {
  type: AssetType;
  id: number;
  name: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const entries: MenuEntry[] = [
    {
      key: "edit",
      label: "Edit",
      icon: <Pencil />,
      run: onEdit,
    },
    {
      key: "delete",
      label: "Delete",
      icon: <Trash2 />,
      destructive: true,
      separatorBefore: true,
      run: onDelete,
    },
  ];

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
        <DropdownMenuContent align="end" className="w-36">
          {entries.map((e) => (
            <div key={e.key} className="contents">
              {e.separatorBefore ? <DropdownMenuSeparator /> : null}
              <DropdownMenuItem
                variant={e.destructive ? "destructive" : "default"}
                onClick={e.run}
              >
                {e.icon}
                {e.label}
              </DropdownMenuItem>
            </div>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
