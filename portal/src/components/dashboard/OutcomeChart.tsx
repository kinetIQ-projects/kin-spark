import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
  Tooltip,
} from "recharts";
import type { OutcomeBucket } from "@/lib/types";
import { Skeleton } from "@/components/common/Skeleton";

const OUTCOME_COLORS: Record<string, string> = {
  completed: "#22c55e",
  lead_captured: "#a855f7",
  terminated: "#ef4444",
  abandoned: "#9ca3af",
};

const DEFAULT_COLOR = "#6366f1";

interface OutcomeChartProps {
  data?: OutcomeBucket[];
  isLoading: boolean;
}

export function OutcomeChart({ data, isLoading }: OutcomeChartProps) {
  if (isLoading) {
    return <Skeleton className="h-[250px] w-full" />;
  }

  if (!data || data.length === 0) {
    return (
      <div className="flex h-[250px] items-center justify-center text-sm text-muted-foreground">
        No outcome data
      </div>
    );
  }

  const formatted = data.map((d) => ({
    ...d,
    label: d.outcome.replace("_", " "),
  }));

  return (
    <div className="h-[250px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={formatted}
            dataKey="count"
            nameKey="label"
            cx="50%"
            cy="45%"
            innerRadius={50}
            outerRadius={80}
          >
            {formatted.map((entry) => (
              <Cell
                key={entry.outcome}
                fill={OUTCOME_COLORS[entry.outcome] ?? DEFAULT_COLOR}
              />
            ))}
          </Pie>
          <Tooltip
            contentStyle={{
              borderRadius: "0.5rem",
              border: "1px solid hsl(var(--border))",
              fontSize: "0.875rem",
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: "0.75rem" }}
            formatter={(value: string) => (
              <span className="text-foreground">{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
