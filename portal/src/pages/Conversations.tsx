import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { ConversationListItem, PaginatedResponse } from "@/lib/types";
import { formatDate, formatDuration } from "@/lib/utils";
import { OutcomeBadge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { Pagination } from "@/components/common/Pagination";
import { TableSkeleton } from "@/components/common/Skeleton";
import { ErrorCard } from "@/components/common/ErrorCard";
import { toast } from "@/components/ui/toaster";

const OUTCOMES = ["", "active", "completed", "lead_captured", "terminated", "abandoned"];

export function Conversations() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [outcome, setOutcome] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const limit = 50;

  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (outcome) params.set("outcome", outcome);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["conversations", offset, outcome, dateFrom, dateTo],
    queryFn: () =>
      apiFetch<PaginatedResponse<ConversationListItem>>(
        `/conversations?${params.toString()}`
      ),
    refetchInterval: 30_000,
  });

  if (isError) {
    toast("Failed to load conversations", "destructive");
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Conversations</h1>

      {/* Filters */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          value={outcome}
          onChange={(e) => {
            setOutcome(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">All outcomes</option>
          {OUTCOMES.filter(Boolean).map((o) => (
            <option key={o} value={o}>
              {o.replace("_", " ")}
            </option>
          ))}
        </select>

        <input
          type="date"
          value={dateFrom}
          onChange={(e) => {
            setDateFrom(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
          placeholder="From date"
        />

        <input
          type="date"
          value={dateTo}
          onChange={(e) => {
            setDateTo(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
          placeholder="To date"
        />
      </div>

      {/* Table */}
      <div className="mt-4 rounded-lg border">
        {isLoading ? (
          <div className="py-4">
            <TableSkeleton rows={8} />
          </div>
        ) : isError ? (
          <div className="p-4">
            <ErrorCard message="Failed to load conversations" onRetry={() => refetch()} />
          </div>
        ) : !data?.items.length ? (
          <EmptyState
            icon={MessageSquare}
            title="No conversations yet"
            description="Conversations will appear here as visitors chat with your AI rep."
          />
        ) : (
          <>
            {/* Header */}
            <div className="hidden border-b bg-muted/50 px-4 py-2 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[1fr_3fr_80px_100px_100px]">
              <span>Date</span>
              <span>Preview</span>
              <span>Turns</span>
              <span>Outcome</span>
              <span>Duration</span>
            </div>

            {/* Rows */}
            {data.items.map((conv) => (
              <div
                key={conv.id}
                onClick={() => navigate(`/conversations/${conv.id}`)}
                className="cursor-pointer border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/50 md:grid md:grid-cols-[1fr_3fr_80px_100px_100px] md:items-center"
              >
                <span className="text-sm text-muted-foreground">
                  {formatDate(conv.created_at)}
                </span>
                <span className="mt-1 block text-sm md:mt-0">
                  {conv.first_message_preview || (
                    <span className="italic text-muted-foreground">
                      No preview
                    </span>
                  )}
                </span>
                <span className="text-sm text-muted-foreground">
                  {conv.turn_count}
                </span>
                <div>
                  <OutcomeBadge outcome={conv.outcome ?? conv.state} />
                </div>
                <span className="text-sm text-muted-foreground">
                  {conv.duration_seconds
                    ? formatDuration(conv.duration_seconds)
                    : "—"}
                </span>
              </div>
            ))}

            <Pagination
              total={data.total}
              limit={limit}
              offset={offset}
              onOffsetChange={setOffset}
            />
          </>
        )}
      </div>
    </div>
  );
}
