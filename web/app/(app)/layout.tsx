import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { gateMode } from "@/lib/session";

export default function AppLayout({ children }: LayoutProps<"/">) {
  // Resolved at build/prerender time (env changes require a redeploy), so the
  // sidebar is part of the static shell and identical on server and client.
  const showLogout = gateMode() !== "disabled";
  return (
    <SidebarProvider>
      <AppSidebar showLogout={showLogout} />
      <SidebarInset>
        <SiteHeader />
        <div className="mx-auto w-full min-w-0 max-w-7xl flex-1 px-3 py-6 md:px-4">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
