import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { LayoutDashboard } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type {
  DashboardSummary,
  DashboardTimeseries,
  DateRange,
} from "@/lib/types";
import { KpiCards } from "@/components/dashboard/KpiCards";
import { DateRangeSelector } from "@/components/dashboard/DateRangeSelector";
import { ConversationsChart } from "@/components/dashboard/ConversationsChart";
import { OutcomeChart } from "@/components/dashboard/OutcomeChart";
import { SentimentChart } from "@/components/dashboard/SentimentChart";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorCard } from "@/components/common/ErrorCard";

export function Dashboard() {
  const [dateRange, setDateRange] = useState<DateRange>(7);

  const summary = useQuery({
    queryKey: ["metrics-summary", dateRange],
    queryFn: () =>
      apiFetch<DashboardSummary>(`/metrics/summary?days=${dateRange}`),
  });

  const timeseries = useQuery({
    queryKey: ["metrics-timeseries", dateRange],
    queryFn: () =>
      apiFetch<DashboardTimeseries>(`/metrics/timeseries?days=${dateRange}`),
  });

  const isLoading = summary.isLoading || timeseries.isLoading;
  const isError = summary.isError || timeseries.isError;
  const isEmpty =
    !isLoading &&
    !isError &&
    summary.data?.total_conversations === 0;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <DateRangeSelector value={dateRange} onChange={setDateRange} />
      </div>

      {isError ? (
        <div className="mt-8">
          <ErrorCard
            message="Failed to load dashboard metrics"
            onRetry={() => {
              summary.refetch();
              timeseries.refetch();
            }}
          />
        </div>
      ) : isEmpty ? (
        <div className="mt-8">
          <EmptyState
            icon={LayoutDashboard}
            title="No conversations yet"
            description="Metrics will appear here once visitors start chatting with your AI rep."
          />
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="mt-6">
            <KpiCards data={summary.data} isLoading={summary.isLoading} />
          </div>

          {/* Charts */}
          <div className="mt-6 grid gap-6 lg:grid-cols-2">
            {/* Activity chart — full width on large screens */}
            <div className="rounded-lg border p-4 lg:col-span-2">
              <h2 className="mb-4 text-sm font-medium text-muted-foreground">
                Activity
              </h2>
              <ConversationsChart
                data={timeseries.data?.daily}
                isLoading={timeseries.isLoading}
              />
            </div>

            {/* Outcome donut */}
            <div className="rounded-lg border p-4">
              <h2 className="mb-4 text-sm font-medium text-muted-foreground">
                Outcomes
              </h2>
              <OutcomeChart
                data={timeseries.data?.outcomes}
                isLoading={timeseries.isLoading}
              />
            </div>

            {/* Sentiment bars */}
            <div className="rounded-lg border p-4">
              <h2 className="mb-4 text-sm font-medium text-muted-foreground">
                Sentiment
              </h2>
              <SentimentChart
                data={timeseries.data?.sentiments}
                isLoading={timeseries.isLoading}
              />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
