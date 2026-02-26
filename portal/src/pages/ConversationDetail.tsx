import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, User, Bot, Clock, MessageSquare, Users } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { ConversationDetail as ConvDetail } from "@/lib/types";
import { formatDate, formatDuration, cn } from "@/lib/utils";
import { OutcomeBadge, LeadStatusBadge } from "@/components/common/Badge";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorCard } from "@/components/common/ErrorCard";

export function ConversationDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => apiFetch<ConvDetail>(`/conversations/${id}`),
    refetchOnWindowFocus: true,
  });

  if (isLoading) {
    return <LoadingSpinner className="mt-20" />;
  }

  if (isError || !data) {
    return (
      <div className="mt-8">
        <ErrorCard message="Failed to load conversation" onRetry={() => refetch()} />
      </div>
    );
  }

  return (
    <div>
      {/* Back button */}
      <button
        onClick={() => navigate("/conversations")}
        className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to conversations
      </button>

      <div className="grid gap-6 lg:grid-cols-[1fr_300px]">
        {/* Transcript */}
        <div className="rounded-lg border">
          <div className="border-b px-4 py-3">
            <h2 className="font-medium">Transcript</h2>
            <p className="text-sm text-muted-foreground">
              {data.turn_count} turns
            </p>
          </div>

          <div className="space-y-4 p-4">
            {data.messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex gap-3",
                  msg.role === "user" ? "flex-row-reverse" : "flex-row"
                )}
              >
                <div
                  className={cn(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
                    msg.role === "user"
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground"
                  )}
                >
                  {msg.role === "user" ? (
                    <User className="h-4 w-4" />
                  ) : (
                    <Bot className="h-4 w-4" />
                  )}
                </div>
                <div
                  className={cn(
                    "max-w-[80%] rounded-lg px-4 py-2",
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted"
                  )}
                >
                  <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
                  <p
                    className={cn(
                      "mt-1 text-xs",
                      msg.role === "user"
                        ? "text-primary-foreground/70"
                        : "text-muted-foreground"
                    )}
                  >
                    {formatDate(msg.created_at)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Metadata sidebar */}
        <div className="space-y-4">
          {/* Conversation info */}
          <div className="rounded-lg border p-4">
            <h3 className="text-sm font-medium">Details</h3>
            <dl className="mt-3 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">Started</dt>
                <dd>{formatDate(data.created_at)}</dd>
              </div>
              {data.ended_at && (
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">Ended</dt>
                  <dd>{formatDate(data.ended_at)}</dd>
                </div>
              )}
              {data.duration_seconds != null && (
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">Duration</dt>
                  <dd className="flex items-center gap-1">
                    <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                    {formatDuration(data.duration_seconds)}
                  </dd>
                </div>
              )}
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">Turns</dt>
                <dd className="flex items-center gap-1">
                  <MessageSquare className="h-3.5 w-3.5 text-muted-foreground" />
                  {data.turn_count}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">Outcome</dt>
                <dd>
                  <OutcomeBadge outcome={data.outcome ?? data.state} />
                </dd>
              </div>
              {data.sentiment && (
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">Sentiment</dt>
                  <dd>{data.sentiment}</dd>
                </div>
              )}
              {data.summary && (
                <div>
                  <dt className="text-muted-foreground">Summary</dt>
                  <dd className="mt-1 text-xs leading-relaxed">
                    {data.summary}
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* Lead card */}
          {data.lead && (
            <div className="rounded-lg border p-4">
              <div className="flex items-center gap-2">
                <Users className="h-4 w-4 text-muted-foreground" />
                <h3 className="text-sm font-medium">Lead Captured</h3>
              </div>
              <dl className="mt-3 space-y-2 text-sm">
                {data.lead.name && (
                  <div className="flex items-center justify-between">
                    <dt className="text-muted-foreground">Name</dt>
                    <dd>{data.lead.name}</dd>
                  </div>
                )}
                {data.lead.email && (
                  <div className="flex items-center justify-between">
                    <dt className="text-muted-foreground">Email</dt>
                    <dd>{data.lead.email}</dd>
                  </div>
                )}
                {data.lead.phone && (
                  <div className="flex items-center justify-between">
                    <dt className="text-muted-foreground">Phone</dt>
                    <dd>{data.lead.phone}</dd>
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <dt className="text-muted-foreground">Status</dt>
                  <dd>
                    <LeadStatusBadge status={data.lead.status} />
                  </dd>
                </div>
              </dl>
              <Link
                to="/leads"
                className="mt-3 block text-xs text-primary hover:underline"
              >
                View in Leads
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
