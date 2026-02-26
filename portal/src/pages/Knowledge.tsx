import { BookOpen } from "lucide-react";
import { EmptyState } from "@/components/common/EmptyState";

export function Knowledge() {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Knowledge Base</h1>
      <div className="mt-8">
        <EmptyState
          icon={BookOpen}
          title="Knowledge management coming soon"
          description="Upload and manage your AI rep's knowledge base in Phase 5."
        />
      </div>
    </div>
  );
}
