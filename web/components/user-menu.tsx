"use client";

import { useEffect, useState, useTransition } from "react";
import { LogOut, Pencil } from "lucide-react";
import { logout } from "@/app/actions/auth";
import { EditNameDialog } from "@/components/edit-name-dialog";
import { initials } from "@/lib/profile";
import { clearSearchData } from "@/components/search/search-store";
import { Button } from "@/components/ui/button";
import { invalidateNetWorth } from "@/lib/networth-cache";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function UserMenu() {
  const [email, setEmail] = useState<string | null>(null);
  const [fullName, setFullName] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/me", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((me: { email?: string; full_name?: string | null } | null) => {
        if (!cancelled && me?.email) {
          setEmail(me.email);
          setFullName(me.full_name ?? null);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!email) {
    return (
      <div
        aria-hidden
        className="size-8 shrink-0 rounded-lg border border-border bg-muted"
      />
    );
  }

  return (
    <>
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            aria-label="Account menu"
            variant="secondary"
            className="size-8 shrink-0 rounded-lg border border-border p-0 text-xs font-semibold text-foreground hover:bg-accent"
          />
        }
      >
        {initials(fullName, email)}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto min-w-0 max-w-64">
        <DropdownMenuGroup>
          {fullName ? (
            <DropdownMenuLabel className="flex flex-col gap-0.5" title={email}>
              <span className="truncate font-medium text-foreground">{fullName}</span>
              <span className="truncate font-normal text-muted-foreground">{email}</span>
            </DropdownMenuLabel>
          ) : (
            <DropdownMenuLabel className="truncate font-normal" title={email}>
              Signed in as {email}
            </DropdownMenuLabel>
          )}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => setEditing(true)}>
          <Pencil />
          Edit Name
        </DropdownMenuItem>
        <DropdownMenuItem
          onClick={() => {
            clearSearchData();
            invalidateNetWorth();
            startTransition(() => logout());
          }}
        >
          <LogOut />
          Log Out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
    <EditNameDialog
      open={editing}
      onOpenChange={setEditing}
      initialName={fullName}
      onSaved={setFullName}
    />
    </>
  );
}
