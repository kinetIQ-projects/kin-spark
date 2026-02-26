import { LayoutDashboard } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export function Dashboard() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
      <div className="mt-8">
        <EmptyState
          icon={LayoutDashboard}
          title="Dashboard coming soon"
          description="Analytics and metrics will appear here in Phase 4."
        />
      </div>
    </div>
  );
}
