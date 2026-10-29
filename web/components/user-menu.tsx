"use client";

import { useEffect, useState, useTransition } from "react";
import { LogOut } from "lucide-react";
import { logout } from "@/app/actions/auth";
import { Button } from "@/components/ui/button";
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
  const [, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/me", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((me: { email?: string } | null) => {
        if (!cancelled && me?.email) setEmail(me.email);
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
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            aria-label="Account menu"
            variant="secondary"
            className="size-8 shrink-0 rounded-lg border border-border p-0 text-sm font-semibold text-foreground hover:bg-accent"
          />
        }
      >
        {email.charAt(0).toUpperCase()}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto min-w-0 max-w-64">
        <DropdownMenuGroup>
          <DropdownMenuLabel
            className="truncate px-2 py-1 text-xs font-normal text-muted-foreground"
            title={email}
          >
            {email}
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          className="gap-1.5 py-1 text-xs"
          onClick={() => startTransition(() => logout())}
        >
          <LogOut className="size-3.5" />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
