import { FileText, Trash2, Loader2, Check, AlertCircle, Image } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils";
import type { FileUpload } from "@/lib/types";

const STATUS_CONFIG: Record<
  string,
  { label: string; color: string; icon: typeof Check }
> = {
  uploaded: { label: "Uploaded", color: "text-muted-foreground", icon: Loader2 },
  parsing: { label: "Parsing...", color: "text-yellow-600", icon: Loader2 },
  parsed: { label: "Parsed", color: "text-green-600", icon: Check },
  failed: { label: "Failed", color: "text-destructive", icon: AlertCircle },
};

const MIME_ICONS: Record<string, typeof FileText> = {
  "application/pdf": FileText,
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileText,
  "text/plain": FileText,
  "image/png": Image,
  "image/jpeg": Image,
  "image/webp": Image,
};

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface FileUploadListProps {
  uploads: FileUpload[];
  onDelete: (id: string) => void;
  isDeleting?: string | null;
}

export function FileUploadList({
  uploads,
  onDelete,
  isDeleting,
}: FileUploadListProps) {
  if (uploads.length === 0) return null;

  return (
    <div className="space-y-2">
      {uploads.map((upload) => {
        const status = STATUS_CONFIG[upload.status] ?? STATUS_CONFIG.uploaded;
        const Icon = MIME_ICONS[upload.mime_type] ?? FileText;
        const StatusIcon = status.icon;

        return (
          <div
            key={upload.id}
            className="flex items-center gap-3 rounded-md border px-3 py-2.5"
          >
            <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />

            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {upload.original_name}
              </p>
              <p className="text-xs text-muted-foreground">
                {formatFileSize(upload.file_size)}
                {upload.page_count != null && ` \u00B7 ${upload.page_count} pages`}
                {" \u00B7 "}
                {formatDate(upload.created_at)}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <span
                className={cn(
                  "flex items-center gap-1 text-xs font-medium",
                  status.color
                )}
              >
                <StatusIcon
                  className={cn(
                    "h-3.5 w-3.5",
                    upload.status === "parsing" && "animate-spin"
                  )}
                />
                {status.label}
              </span>

              <button
                onClick={() => onDelete(upload.id)}
                disabled={isDeleting === upload.id}
                className="rounded-md p-1 text-muted-foreground transition-colors hover:text-destructive disabled:opacity-50"
                title="Delete upload"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>

            {upload.error_message && (
              <p className="mt-1 w-full text-xs text-destructive">
                {upload.error_message}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
