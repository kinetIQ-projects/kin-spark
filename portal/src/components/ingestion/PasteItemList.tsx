import { Trash2, FileText } from "lucide-react";
import { formatDate } from "@/lib/utils";
import type { PasteItem } from "@/lib/types";

interface PasteItemListProps {
  items: PasteItem[];
  onDelete: (id: string) => void;
  isDeleting?: string | null;
}

export function PasteItemList({
  items,
  onDelete,
  isDeleting,
}: PasteItemListProps) {
  if (items.length === 0) return null;

  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div
          key={item.id}
          className="flex items-start gap-3 rounded-md border px-3 py-2.5"
        >
          <FileText className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />

          <div className="min-w-0 flex-1">
            {item.title && (
              <p className="truncate text-sm font-medium">{item.title}</p>
            )}
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {item.content}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {item.content.length.toLocaleString()} chars
              {" \u00B7 "}
              {formatDate(item.created_at)}
            </p>
          </div>

          <button
            onClick={() => onDelete(item.id)}
            disabled={isDeleting === item.id}
            className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50"
            title="Delete paste item"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}
