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
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="flex flex-col gap-0.5">
            <span className="text-xs font-normal text-muted-foreground">
              Signed in as
            </span>
            <span className="truncate text-sm text-foreground" title={email}>
              {email}
            </span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => startTransition(() => logout())}>
          <LogOut />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
