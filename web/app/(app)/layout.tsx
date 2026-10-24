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
        <div className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
