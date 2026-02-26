import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Users, Download } from "lucide-react";
import { apiFetch, apiFetchBlob } from "@/lib/api";
import type { LeadListItem, LeadUpdate, PaginatedResponse } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { LeadStatusBadge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { Pagination } from "@/components/common/Pagination";
import { TableSkeleton } from "@/components/common/Skeleton";
import { ErrorCard } from "@/components/common/ErrorCard";
import { LeadDetailPanel } from "@/components/leads/LeadDetailPanel";
import { toast } from "@/components/ui/toaster";

const STATUSES = ["", "new", "contacted", "converted", "lost"];

export function Leads() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedLead, setSelectedLead] = useState<LeadListItem | null>(null);
  const limit = 50;

  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (status) params.set("status", status);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["leads", offset, status, dateFrom, dateTo],
    queryFn: () =>
      apiFetch<PaginatedResponse<LeadListItem>>(
        `/leads?${params.toString()}`
      ),
    refetchInterval: 30_000,
  });

  // Optimistic lead update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, update }: { id: string; update: LeadUpdate }) =>
      apiFetch<LeadListItem>(`/leads/${id}`, {
        method: "PATCH",
        body: JSON.stringify(update),
      }),
    onMutate: async ({ id, update }) => {
      await queryClient.cancelQueries({ queryKey: ["leads"] });
      const previous = queryClient.getQueryData<PaginatedResponse<LeadListItem>>([
        "leads",
        offset,
        status,
        dateFrom,
        dateTo,
      ]);

      // Optimistic update
      if (previous) {
        queryClient.setQueryData<PaginatedResponse<LeadListItem>>(
          ["leads", offset, status, dateFrom, dateTo],
          {
            ...previous,
            items: previous.items.map((l) =>
              l.id === id ? { ...l, ...update } : l
            ),
          }
        );
      }

      return { previous };
    },
    onError: (_err, _vars, context) => {
      // Rollback
      if (context?.previous) {
        queryClient.setQueryData(
          ["leads", offset, status, dateFrom, dateTo],
          context.previous
        );
      }
      toast("Failed to update lead", "destructive");
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  const handleUpdateLead = useCallback(
    (id: string, update: LeadUpdate) => {
      updateMutation.mutate({ id, update });

      // Also update the selected lead panel
      if (selectedLead?.id === id) {
        setSelectedLead((prev) => (prev ? { ...prev, ...update } : prev));
      }
    },
    [updateMutation, selectedLead]
  );

  async function handleExport() {
    try {
      const exportParams = new URLSearchParams();
      if (status) exportParams.set("status", status);
      if (dateFrom) exportParams.set("date_from", dateFrom);
      if (dateTo) exportParams.set("date_to", dateTo);

      const blob = await apiFetchBlob(
        `/leads/export?${exportParams.toString()}`
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `spark-leads-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast("Failed to export leads", "destructive");
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Leads</h1>
        <button
          onClick={handleExport}
          disabled={!data?.items.length}
          className="inline-flex items-center gap-1.5 rounded-md border bg-background px-3 py-1.5 text-sm font-medium shadow-sm transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
        >
          <Download className="h-4 w-4" />
          Export CSV
        </button>
      </div>

      {/* Filters */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">All statuses</option>
          {STATUSES.filter(Boolean).map((s) => (
            <option key={s} value={s}>
              {s}
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
        />
        <input
          type="date"
          value={dateTo}
          onChange={(e) => {
            setDateTo(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
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
            <ErrorCard message="Failed to load leads" onRetry={() => refetch()} />
          </div>
        ) : !data?.items.length ? (
          <EmptyState
            icon={Users}
            title="No leads yet"
            description="Leads captured during conversations will appear here."
          />
        ) : (
          <>
            {/* Header */}
            <div className="hidden border-b bg-muted/50 px-4 py-2 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[1.5fr_2fr_1fr_1fr_80px]">
              <span>Name</span>
              <span>Email</span>
              <span>Phone</span>
              <span>Date</span>
              <span>Status</span>
            </div>

            {/* Rows */}
            {data.items.map((lead) => (
              <div
                key={lead.id}
                onClick={() => setSelectedLead(lead)}
                className="cursor-pointer border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/50 md:grid md:grid-cols-[1.5fr_2fr_1fr_1fr_80px] md:items-center"
              >
                <span className="text-sm font-medium">
                  {lead.name || (
                    <span className="text-muted-foreground">—</span>
                  )}
                </span>
                <span className="text-sm text-muted-foreground">
                  {lead.email || "—"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {lead.phone || "—"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {formatDate(lead.created_at)}
                </span>
                <div>
                  <LeadStatusBadge status={lead.status} />
                </div>
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

      {/* Detail Panel */}
      {selectedLead && (
        <LeadDetailPanel
          lead={selectedLead}
          onClose={() => setSelectedLead(null)}
          onUpdate={handleUpdateLead}
        />
      )}
    </div>
  );
}
