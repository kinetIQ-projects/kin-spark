import type { DashboardSummary } from "@/lib/types";
import { formatDuration } from "@/lib/utils";
import { Skeleton } from "@/components/common/Skeleton";

interface KpiCardsProps {
  data?: DashboardSummary;
  isLoading: boolean;
}

export function KpiCards({ data, isLoading }: KpiCardsProps) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="rounded-lg border p-4">
            <Skeleton className="mb-2 h-3 w-20" />
            <Skeleton className="h-7 w-16" />
          </div>
        ))}
      </div>
    );
  }

  if (!data) return null;

  const cards = [
    {
      label: "Conversations",
      value: data.total_conversations.toLocaleString(),
    },
    {
      label: "Leads captured",
      value: data.total_leads.toLocaleString(),
    },
    {
      label: "Conversion rate",
      value: `${(data.conversion_rate * 100).toFixed(1)}%`,
      sublabel: "of conversations",
    },
    {
      label: "Avg turns",
      value: data.avg_turns.toFixed(1),
    },
    {
      label: "Avg duration",
      value:
        data.avg_duration_seconds != null
          ? formatDuration(Math.round(data.avg_duration_seconds))
          : "—",
      sublabel:
        data.conversations_with_duration > 0
          ? `based on ${data.conversations_with_duration} conversation${data.conversations_with_duration === 1 ? "" : "s"}`
          : undefined,
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
      {cards.map((card) => (
        <div key={card.label} className="rounded-lg border p-4">
          <p className="text-xs font-medium text-muted-foreground">
            {card.label}
          </p>
          <p className="mt-1 text-2xl font-semibold tracking-tight">
            {card.value}
          </p>
          {card.sublabel && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {card.sublabel}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
