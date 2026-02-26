import { Settings as SettingsIcon } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export function Settings() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
      <div className="mt-8">
        <EmptyState
          icon={SettingsIcon}
          title="Settings coming soon"
          description="Widget configuration and integrations will be available in Phase 6."
        />
      </div>
    </div>
  );
}
