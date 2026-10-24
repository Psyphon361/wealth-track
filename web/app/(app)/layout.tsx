import { Suspense } from "react";
import { connection } from "next/server";
import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { gateMode } from "@/lib/session";

async function Sidebar() {
  // Read env at request time, not build time.
  await connection();
  return <AppSidebar showLogout={gateMode() !== "disabled"} />;
}

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SidebarProvider>
      <Suspense fallback={null}>
        <Sidebar />
      </Suspense>
      <SidebarInset>
        <SiteHeader />
        <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 md:px-6">
          {children}
        </main>
      </SidebarInset>
    </SidebarProvider>
  );
}
