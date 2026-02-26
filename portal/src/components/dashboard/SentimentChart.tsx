import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";
import type { SentimentBucket } from "@/lib/types";
import { Skeleton } from "@/components/common/Skeleton";

const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#22c55e",
  neutral: "#9ca3af",
  negative: "#ef4444",
};

const DEFAULT_COLOR = "#6366f1";

interface SentimentChartProps {
  data?: SentimentBucket[];
  isLoading: boolean;
}

export function SentimentChart({ data, isLoading }: SentimentChartProps) {
  if (isLoading) {
    return <Skeleton className="h-[250px] w-full" />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-muted-foreground">
        No sentiment data
      </div>
    );
  }

  return (
    <div className="h-[250px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
          <XAxis type="number" allowDecimals={false} tick={{ fontSize: 12 }} />
          <YAxis
            type="category"
            dataKey="sentiment"
            tick={{ fontSize: 12 }}
            width={70}
          />
          <Tooltip
            contentStyle={{
              borderRadius: "0.5rem",
              border: "1px solid hsl(var(--border))",
              fontSize: "0.875rem",
            }}
          />
          <Bar dataKey="count" name="Conversations" radius={[0, 4, 4, 0]}>
            {data.map((entry) => (
              <Cell
                key={entry.sentiment}
                fill={SENTIMENT_COLORS[entry.sentiment] ?? DEFAULT_COLOR}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
