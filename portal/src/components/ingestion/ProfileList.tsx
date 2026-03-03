import { useState } from "react";
import { FileText, ChevronDown, ChevronUp, Check, MessageSquare } from "lucide-react";
import type { Profile } from "@/lib/types";
import { PROFILE_TYPE_LABELS } from "@/lib/types";

const STATUS_BADGES: Record<string, { label: string; className: string }> = {
  draft: { label: "Draft", className: "bg-yellow-100 text-yellow-800" },
  pending_review: { label: "Pending Review", className: "bg-blue-100 text-blue-800" },
  approved: { label: "Approved", className: "bg-green-100 text-green-800" },
  rejected: { label: "Changes Requested", className: "bg-red-100 text-red-800" },
};

interface ProfileListProps {
  profiles: Profile[];
  onApprove?: (id: string) => void;
  onRequestChanges?: (id: string, feedback: string) => void;
  isUpdating?: string | null;
}

export function ProfileList({
  profiles,
  onApprove,
  onRequestChanges,
  isUpdating,
}: ProfileListProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [feedbackId, setFeedbackId] = useState<string | null>(null);
  const [feedbackText, setFeedbackText] = useState("");

  if (profiles.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">
        No profiles generated yet. Run the pipeline to create profiles.
      </p>
    );
  }

  const handleRequestChanges = (profileId: string) => {
    if (!feedbackText.trim() || !onRequestChanges) return;
    onRequestChanges(profileId, feedbackText.trim());
    setFeedbackId(null);
    setFeedbackText("");
  };

  return (
    <div className="space-y-2">
      {profiles.map((profile) => {
        const isExpanded = expandedId === profile.id;
        const badge = STATUS_BADGES[profile.status] ?? STATUS_BADGES.draft;
        const label =
          PROFILE_TYPE_LABELS[profile.profile_type] ?? profile.profile_type;
        const showActions = profile.status !== "approved" && onApprove;
        const isShowingFeedback = feedbackId === profile.id;
        const busy = isUpdating === profile.id;

        return (
          <div
            key={profile.id}
            className="rounded-md border bg-card"
          >
            <button
              onClick={() => setExpandedId(isExpanded ? null : profile.id)}
              className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm hover:bg-muted/50 transition-colors"
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="font-medium truncate">{label}</span>
                <span className="text-xs text-muted-foreground">v{profile.version}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${badge.className}`}
                >
                  {badge.label}
                </span>
                {isExpanded ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </div>
            </button>

            {isExpanded && (
              <div className="border-t px-4 py-3">
                <pre className="whitespace-pre-wrap text-sm text-foreground/90 max-h-96 overflow-y-auto font-sans leading-relaxed">
                  {profile.content}
                </pre>

                {/* Previous feedback */}
                {profile.client_feedback && (
                  <div className="mt-3 rounded-md bg-red-50 border border-red-200 px-3 py-2">
                    <p className="text-xs font-medium text-red-800">Previous feedback:</p>
                    <p className="mt-1 text-sm text-red-700">{profile.client_feedback}</p>
                  </div>
                )}

                <div className="mt-3 flex items-center justify-between">
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <span>
                      Created{" "}
                      {new Date(profile.created_at).toLocaleDateString()}
                    </span>
                    {profile.reviewed_at && (
                      <span>
                        Reviewed{" "}
                        {new Date(profile.reviewed_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  {/* Action buttons */}
                  {showActions && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setFeedbackId(isShowingFeedback ? null : profile.id);
                          setFeedbackText("");
                        }}
                        disabled={busy}
                        className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-50"
                      >
                        <MessageSquare className="h-3 w-3" />
                        Request Changes
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onApprove?.(profile.id);
                        }}
                        disabled={busy}
                        className="inline-flex items-center gap-1 rounded-md bg-green-600 px-2.5 py-1.5 text-xs font-medium text-white transition-colors hover:bg-green-700 disabled:opacity-50"
                      >
                        <Check className="h-3 w-3" />
                        {busy ? "Updating..." : "Approve"}
                      </button>
                    </div>
                  )}
                </div>

                {/* Feedback form */}
                {isShowingFeedback && (
                  <div className="mt-3 space-y-2">
                    <textarea
                      value={feedbackText}
                      onChange={(e) => setFeedbackText(e.target.value)}
                      placeholder="Describe what changes you'd like..."
                      rows={3}
                      className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    />
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => {
                          setFeedbackId(null);
                          setFeedbackText("");
                        }}
                        className="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleRequestChanges(profile.id)}
                        disabled={!feedbackText.trim() || busy}
                        className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
                      >
                        Submit Feedback
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
