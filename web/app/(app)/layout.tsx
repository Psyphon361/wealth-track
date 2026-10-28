import { AppSidebar } from "@/components/app-sidebar";
import { SiteHeader } from "@/components/site-header";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <SiteHeader />
        <div className="mx-auto w-full min-w-0 max-w-7xl flex-1 px-3 py-6 md:px-4">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
