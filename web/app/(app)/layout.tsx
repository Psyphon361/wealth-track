import { Suspense } from "react";
import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SidebarProvider>
      <Suspense>
        <AppSidebar />
      </Suspense>
      <SidebarInset>
        <Suspense
          fallback={
            <header className="sticky top-0 z-10 h-12 shrink-0 border-b bg-background/80 md:rounded-t-xl" />
          }
        >
          <SiteHeader />
        </Suspense>
        <div className="mx-auto w-full min-w-0 max-w-7xl flex-1 px-3 py-6 md:px-4">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
