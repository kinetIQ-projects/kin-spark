import { useQuery } from "@tanstack/react-query";
import {
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  Ban,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import { apiFetch } from "@/lib/api";
import type { PipelineRun } from "@/lib/types";

const STAGE_LABELS: Record<string, string> = {
  gathering: "Gathering Sources",
  stage_0_scrape: "Web Scraping",
  stage_1: "Classifying Content",
  stage_2: "Cross-Referencing",
  stage_3: "Extracting Profiles",
  completed: "Complete",
  cancelled: "Cancelled",
};

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: typeof CheckCircle2 }
> = {
  pending: { label: "Pending", color: "text-muted-foreground", icon: Clock },
  stage_0_scrape: { label: "Scraping", color: "text-blue-600", icon: Loader2 },
  stage_1: { label: "Classifying", color: "text-blue-600", icon: Loader2 },
  stage_2: { label: "Cross-Referencing", color: "text-blue-600", icon: Loader2 },
  stage_3: { label: "Extracting", color: "text-blue-600", icon: Loader2 },
  completed: { label: "Completed", color: "text-green-600", icon: CheckCircle2 },
  failed: { label: "Failed", color: "text-destructive", icon: XCircle },
  cancelled: { label: "Cancelled", color: "text-muted-foreground", icon: Ban },
};

const ACTIVE_STATUSES = new Set([
  "pending",
  "stage_0_scrape",
  "stage_1",
  "stage_2",
  "stage_3",
]);

interface PipelineStatusProps {
  latestRun: PipelineRun | null;
  onTrigger: () => void;
  onCancel: (runId: string) => void;
  isTriggerPending: boolean;
}

export function PipelineStatus({
  latestRun,
  onTrigger,
  onCancel,
  isTriggerPending,
}: PipelineStatusProps) {
  const isActive = latestRun && ACTIVE_STATUSES.has(latestRun.status);

  // Poll for progress when active
  const { data: polledRun } = useQuery({
    queryKey: ["pipeline-run", latestRun?.id],
    queryFn: () =>
      apiFetch<PipelineRun>(`/ingestion/runs/${latestRun!.id}`),
    enabled: !!isActive,
    refetchInterval: 3000,
  });

  const run = polledRun ?? latestRun;
  const status = run ? STATUS_CONFIG[run.status] ?? STATUS_CONFIG.pending : null;
  const progress = run?.progress;
  const hasCompletedRun = run && !ACTIVE_STATUSES.has(run.status);

  return (
    <div className="space-y-3">
      {run && status && (
        <div className="rounded-md border p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <status.icon
                className={cn(
                  "h-4 w-4",
                  status.color,
                  ACTIVE_STATUSES.has(run.status) && "animate-spin"
                )}
              />
              <span className={cn("text-sm font-medium", status.color)}>
                {status.label}
              </span>
            </div>
            {run.created_at && (
              <span className="text-xs text-muted-foreground">
                {formatDate(run.created_at)}
              </span>
            )}
          </div>

          {/* Progress bar */}
          {progress && ACTIVE_STATUSES.has(run.status) && (
            <div className="mt-3 space-y-1.5">
              <div className="h-2 rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.min(progress.percent, 100)}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                {STAGE_LABELS[progress.stage ?? ""] ?? progress.stage}
                {progress.message ? ` — ${progress.message}` : ""}
              </p>
            </div>
          )}

          {/* Error */}
          {run.error_message && (
            <p className="mt-2 text-xs text-destructive">
              {run.error_message}
            </p>
          )}

          {/* Source summary */}
          {run.source_summary && run.status === "completed" && (
            <p className="mt-2 text-xs text-muted-foreground">
              Processed: {run.source_summary.uploads} uploads,{" "}
              {run.source_summary.paste_items} paste items
              {run.source_summary.questionnaire && ", questionnaire"}
              {run.source_summary.scraped_pages > 0 &&
                `, ${run.source_summary.scraped_pages} scraped pages`}
            </p>
          )}

          {/* Cancel button */}
          {isActive && (
            <button
              onClick={() => onCancel(run.id)}
              className="mt-3 inline-flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-destructive"
            >
              <Ban className="h-3 w-3" />
              Cancel
            </button>
          )}
        </div>
      )}

      {/* Trigger button */}
      <button
        onClick={onTrigger}
        disabled={!!isActive || isTriggerPending}
        className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
      >
        {isTriggerPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        {isActive
          ? "Pipeline Running..."
          : hasCompletedRun
          ? "Re-run Pipeline"
          : "Run Pipeline"}
      </button>
    </div>
  );
}
