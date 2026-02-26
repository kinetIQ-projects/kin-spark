import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { X, MessageSquare } from "lucide-react";
import type { LeadListItem, LeadUpdate } from "@/lib/types";
import { formatDate } from "@/lib/utils";

const STATUSES = ["new", "contacted", "converted", "lost"];

interface LeadDetailPanelProps {
  lead: LeadListItem;
  onClose: () => void;
  onUpdate: (id: string, update: LeadUpdate) => void;
}

export function LeadDetailPanel({
  lead,
  onClose,
  onUpdate,
}: LeadDetailPanelProps) {
  const [notes, setNotes] = useState(lead.admin_notes || "");
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Sync notes when lead changes
  useEffect(() => {
    setNotes(lead.admin_notes || "");
  }, [lead.id, lead.admin_notes]);

  function handleStatusChange(newStatus: string) {
    onUpdate(lead.id, { status: newStatus });
  }

  function handleNotesChange(value: string) {
    setNotes(value);
    // Debounced auto-save
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      onUpdate(lead.id, { admin_notes: value });
    }, 1000);
  }

  // Save on blur immediately
  function handleNotesBlur() {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (notes !== (lead.admin_notes || "")) {
      onUpdate(lead.id, { admin_notes: notes });
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/50"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md overflow-y-auto border-l bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="font-medium">Lead Details</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-6 p-4">
          {/* Contact info */}
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-muted-foreground">
              Contact
            </h3>
            <dl className="space-y-2 text-sm">
              {lead.name && (
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Name</dt>
                  <dd className="font-medium">{lead.name}</dd>
                </div>
              )}
              {lead.email && (
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Email</dt>
                  <dd>
                    <a
                      href={`mailto:${lead.email}`}
                      className="text-primary hover:underline"
                    >
                      {lead.email}
                    </a>
                  </dd>
                </div>
              )}
              {lead.phone && (
                <div className="flex justify-between">
                  <dt className="text-muted-foreground">Phone</dt>
                  <dd>{lead.phone}</dd>
                </div>
              )}
              <div className="flex justify-between">
                <dt className="text-muted-foreground">Captured</dt>
                <dd>{formatDate(lead.created_at)}</dd>
              </div>
            </dl>
          </div>

          {/* Status */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">
              Status
            </label>
            <div className="flex gap-2">
              {STATUSES.map((s) => (
                <button
                  key={s}
                  onClick={() => handleStatusChange(s)}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                    lead.status === s
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:bg-muted/80"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-muted-foreground">
              Admin Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => handleNotesChange(e.target.value)}
              onBlur={handleNotesBlur}
              rows={4}
              placeholder="Add notes about this lead..."
              className="w-full resize-none rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground">
              Auto-saves after 1 second
            </p>
          </div>

          {/* Visitor notes */}
          {lead.notes && (
            <div className="space-y-2">
              <label className="text-sm font-medium text-muted-foreground">
                Visitor Message
              </label>
              <p className="rounded-md bg-muted p-3 text-sm">{lead.notes}</p>
            </div>
          )}

          {/* Link to conversation */}
          {lead.conversation_id && (
            <Link
              to={`/conversations/${lead.conversation_id}`}
              className="flex items-center gap-2 text-sm text-primary hover:underline"
            >
              <MessageSquare className="h-4 w-4" />
              View conversation transcript
            </Link>
          )}
        </div>
      </div>
    </>
  );
}
