import { useState, useCallback } from "react";
import { Send } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { toast } from "@/components/ui/toaster";

interface PasteAreaProps {
  onSubmit: () => void;
}

export function PasteArea({ onSubmit }: PasteAreaProps) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = useCallback(async () => {
    const trimmed = content.trim();
    if (!trimmed) return;

    setIsSubmitting(true);
    try {
      await apiFetch("/ingestion/paste", {
        method: "POST",
        body: JSON.stringify({
          content: trimmed,
          title: title.trim() || null,
        }),
      });
      setContent("");
      setTitle("");
      toast("Text submitted");
      onSubmit();
    } catch {
      toast("Failed to submit text", "destructive");
    } finally {
      setIsSubmitting(false);
    }
  }, [content, title, onSubmit]);

  return (
    <div className="space-y-3">
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional)"
        maxLength={200}
        className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <textarea
        value={content}
        onChange={(e) => {
          if (e.target.value.length <= 50000) {
            setContent(e.target.value);
          }
        }}
        rows={5}
        placeholder="Paste content here (emails, documents, policies, brand guidelines...)"
        className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          {content.length.toLocaleString()}/50,000
        </span>
        <button
          onClick={handleSubmit}
          disabled={!content.trim() || isSubmitting}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
        >
          <Send className="h-3.5 w-3.5" />
          {isSubmitting ? "Submitting..." : "Submit"}
        </button>
      </div>
    </div>
  );
}
