import { cn } from "@/lib/utils";

type BadgeVariant =
  | "default"
  | "blue"
  | "green"
  | "yellow"
  | "red"
  | "gray"
  | "purple";

const variantClasses: Record<BadgeVariant, string> = {
  default: "bg-primary/10 text-primary",
  blue: "bg-blue-100 text-blue-800",
  green: "bg-green-100 text-green-800",
  yellow: "bg-yellow-100 text-yellow-800",
  red: "bg-red-100 text-red-800",
  gray: "bg-gray-100 text-gray-600",
  purple: "bg-purple-100 text-purple-800",
};

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

export function Badge({ variant = "default", children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        variantClasses[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

// Helpers for outcome/status → variant mapping

const outcomeVariants: Record<string, BadgeVariant> = {
  completed: "green",
  lead_captured: "purple",
  terminated: "red",
  abandoned: "gray",
  active: "blue",
};

export function OutcomeBadge({ outcome }: { outcome: string | null }) {
  if (!outcome) return null;
  return (
    <Badge variant={outcomeVariants[outcome] ?? "default"}>
      {outcome.replace("_", " ")}
    </Badge>
  );
}

const leadStatusVariants: Record<string, BadgeVariant> = {
  new: "blue",
  contacted: "yellow",
  converted: "green",
  lost: "gray",
};

export function LeadStatusBadge({ status }: { status: string }) {
  return (
    <Badge variant={leadStatusVariants[status] ?? "default"}>
      {status}
    </Badge>
  );
}
