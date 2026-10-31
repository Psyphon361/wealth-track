import { Wordmark } from "./nav";

export function Footer() {
  return (
    <footer className="border-t border-border px-4 py-6">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-2 text-xs text-muted-foreground sm:flex-row">
        <Wordmark />
        <span>© 2026 Wealth Tracker</span>
        <span>Made in India</span>
      </div>
    </footer>
  );
}
