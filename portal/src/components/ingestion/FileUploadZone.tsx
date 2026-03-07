import { useCallback, useState } from "react";
import { Upload, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { apiFetch } from "@/lib/api";
import { supabase } from "@/lib/supabase";
import { toast } from "@/components/ui/toaster";
import type { PresignResponse } from "@/lib/types";

const ALLOWED_TYPES = new Set([
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/plain",
  "text/markdown",
  "image/png",
  "image/jpeg",
  "image/webp",
]);

const MAX_SIZE = 50_000_000; // 50MB

interface FileUploadZoneProps {
  onUploadComplete: () => void;
}

export function FileUploadZone({ onUploadComplete }: FileUploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const fileList = Array.from(files);
      if (fileList.length === 0) return;

      setIsUploading(true);
      setUploadError(null);

      for (const file of fileList) {
        try {
          // Validate client-side
          if (!ALLOWED_TYPES.has(file.type)) {
            toast(`Unsupported file type: ${file.name}`, "destructive");
            continue;
          }
          if (file.size > MAX_SIZE) {
            toast(`File too large: ${file.name} (max 50MB)`, "destructive");
            continue;
          }

          // Step 1: Presign
          const presign = await apiFetch<PresignResponse>(
            "/ingestion/uploads/presign",
            {
              method: "POST",
              body: JSON.stringify({
                filename: file.name,
                mime_type: file.type,
                file_size: file.size,
              }),
            }
          );

          // Step 2: Upload to Supabase Storage
          const { error: storageError } = await supabase.storage
            .from("spark-uploads")
            .upload(presign.storage_path, file, {
              contentType: file.type,
              upsert: false,
            });

          if (storageError) {
            throw new Error(`Storage upload failed: ${storageError.message}`);
          }

          // Step 3: Confirm
          await apiFetch(`/ingestion/uploads/${presign.upload_id}/confirm`, {
            method: "POST",
          });

          toast(`Uploaded: ${file.name}`);
        } catch (err) {
          const msg =
            err instanceof Error ? err.message : "Upload failed";
          setUploadError(msg);
          toast(`Failed to upload ${file.name}`, "destructive");
        }
      }

      setIsUploading(false);
      onUploadComplete();
    },
    [onUploadComplete]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        handleFiles(e.target.files);
      }
    },
    [handleFiles]
  );

  return (
    <div className="space-y-2">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-6 py-10 transition-colors",
          isDragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-muted-foreground/50",
          isUploading && "pointer-events-none opacity-50"
        )}
      >
        {isUploading ? (
          <>
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary" />
            <p className="mt-3 text-sm text-muted-foreground">Uploading...</p>
          </>
        ) : (
          <>
            <Upload className="h-8 w-8 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium">
              Drop files here or{" "}
              <label className="cursor-pointer text-primary hover:underline">
                browse
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                  onChange={handleInputChange}
                  className="sr-only"
                />
              </label>
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              PDF, DOCX, TXT, MD, PNG, JPG, WEBP — up to 50MB
            </p>
          </>
        )}
      </div>

      {uploadError && (
        <div className="flex items-center gap-2 rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {uploadError}
        </div>
      )}
    </div>
  );
}
