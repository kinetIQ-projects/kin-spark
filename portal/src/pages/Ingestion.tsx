import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload, ClipboardList, FileText, Zap, Globe, Save, BookOpen } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { toast } from "@/components/ui/toaster";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorCard } from "@/components/common/ErrorCard";
import { FileUploadZone } from "@/components/ingestion/FileUploadZone";
import { FileUploadList } from "@/components/ingestion/FileUploadList";
import { QuestionnaireModal } from "@/components/ingestion/QuestionnaireModal";
import { PasteArea } from "@/components/ingestion/PasteArea";
import { PasteItemList } from "@/components/ingestion/PasteItemList";
import { PipelineStatus } from "@/components/ingestion/PipelineStatus";
import { ProfileList } from "@/components/ingestion/ProfileList";
import type {
  FileUpload,
  PasteItem,
  PipelineRun,
  Profile,
} from "@/lib/types";

// ── API helpers ─────────────────────────────────────────────────

function fetchUploads(): Promise<FileUpload[]> {
  return apiFetch<FileUpload[]>("/ingestion/uploads");
}

function fetchPastes(): Promise<PasteItem[]> {
  return apiFetch<PasteItem[]>("/ingestion/paste");
}

function fetchRuns(): Promise<PipelineRun[]> {
  return apiFetch<PipelineRun[]>("/ingestion/runs");
}

function fetchWebsiteUrl(): Promise<{ website_url: string | null }> {
  return apiFetch<{ website_url: string | null }>("/ingestion/website-url");
}

function fetchProfiles(): Promise<Profile[]> {
  return apiFetch<Profile[]>("/ingestion/profiles");
}

// ── Page ────────────────────────────────────────────────────────

export function Ingestion() {
  const queryClient = useQueryClient();
  const [questionnaireOpen, setQuestionnaireOpen] = useState(false);
  const [deletingUpload, setDeletingUpload] = useState<string | null>(null);
  const [deletingPaste, setDeletingPaste] = useState<string | null>(null);
  const [includeScrape, setIncludeScrape] = useState(false);
  const [websiteUrlInput, setWebsiteUrlInput] = useState<string | null>(null);
  const [updatingProfile, setUpdatingProfile] = useState<string | null>(null);

  // ── Queries ──────────────────────────────────────────────────
  const uploads = useQuery({ queryKey: ["uploads"], queryFn: fetchUploads });
  const pastes = useQuery({ queryKey: ["pastes"], queryFn: fetchPastes });
  const runs = useQuery({ queryKey: ["pipeline-runs"], queryFn: fetchRuns });
  const websiteUrl = useQuery({
    queryKey: ["website-url"],
    queryFn: fetchWebsiteUrl,
  });
  const profiles = useQuery({ queryKey: ["profiles"], queryFn: fetchProfiles });

  const savedUrl = websiteUrl.data?.website_url ?? null;
  const displayUrl = websiteUrlInput ?? savedUrl ?? "";

  const latestRun = runs.data?.[0] ?? null;

  // ── Mutations ────────────────────────────────────────────────

  const deleteUploadMut = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/ingestion/uploads/${id}`, { method: "DELETE" }),
    onMutate: (id) => setDeletingUpload(id),
    onSettled: () => {
      setDeletingUpload(null);
      queryClient.invalidateQueries({ queryKey: ["uploads"] });
    },
    onError: () => toast("Failed to delete upload", "destructive"),
  });

  const deletePasteMut = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/ingestion/paste/${id}`, { method: "DELETE" }),
    onMutate: (id) => setDeletingPaste(id),
    onSettled: () => {
      setDeletingPaste(null);
      queryClient.invalidateQueries({ queryKey: ["pastes"] });
    },
    onError: () => toast("Failed to delete paste item", "destructive"),
  });

  const saveWebsiteUrlMut = useMutation({
    mutationFn: (url: string) =>
      apiFetch("/ingestion/website-url", {
        method: "PUT",
        body: JSON.stringify({ website_url: url || null }),
      }),
    onSuccess: () => {
      toast("Website URL saved");
      setWebsiteUrlInput(null);
      queryClient.invalidateQueries({ queryKey: ["website-url"] });
    },
    onError: () => toast("Failed to save URL", "destructive"),
  });

  const isRerun = latestRun?.status === "completed";

  const triggerPipeline = useMutation({
    mutationFn: () =>
      apiFetch<PipelineRun>("/ingestion/run", {
        method: "POST",
        body: JSON.stringify({
          include_uploads: true,
          include_paste: true,
          include_questionnaire: true,
          include_scrape: includeScrape,
          trigger_type: isRerun ? "rerun" : "manual",
        }),
      }),
    onSuccess: () => {
      toast("Pipeline started");
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs"] });
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Failed to start pipeline";
      toast(msg, "destructive");
    },
  });

  const cancelPipeline = useMutation({
    mutationFn: (runId: string) =>
      apiFetch(`/ingestion/runs/${runId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      toast("Cancellation requested");
      queryClient.invalidateQueries({ queryKey: ["pipeline-runs"] });
    },
    onError: () => toast("Failed to cancel", "destructive"),
  });

  const approveProfile = useMutation({
    mutationFn: (id: string) =>
      apiFetch(`/ingestion/profiles/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "approved" }),
      }),
    onMutate: (id) => setUpdatingProfile(id),
    onSettled: () => {
      setUpdatingProfile(null);
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
    onSuccess: () => toast("Profile approved"),
    onError: () => toast("Failed to approve profile", "destructive"),
  });

  const requestProfileChanges = useMutation({
    mutationFn: ({ id, feedback }: { id: string; feedback: string }) =>
      apiFetch(`/ingestion/profiles/${id}/request-changes`, {
        method: "POST",
        body: JSON.stringify({ feedback }),
      }),
    onMutate: ({ id }) => setUpdatingProfile(id),
    onSettled: () => {
      setUpdatingProfile(null);
      queryClient.invalidateQueries({ queryKey: ["profiles"] });
    },
    onSuccess: () => toast("Feedback submitted"),
    onError: () => toast("Failed to submit feedback", "destructive"),
  });

  // ── Callbacks ────────────────────────────────────────────────

  const refreshUploads = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["uploads"] });
  }, [queryClient]);

  const refreshPastes = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["pastes"] });
  }, [queryClient]);

  // ── Loading / Error ──────────────────────────────────────────

  if (uploads.isLoading || pastes.isLoading || runs.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  if (uploads.isError || pastes.isError || runs.isError) {
    return (
      <div className="mt-8">
        <ErrorCard
          message="Failed to load ingestion data"
          onRetry={() => {
            uploads.refetch();
            pastes.refetch();
            runs.refetch();
          }}
        />
      </div>
    );
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Ingestion</h1>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        Upload documents, answer questions, and paste content. Then run the
        pipeline to generate your voice profile, values, and knowledge base.
      </p>

      <div className="mt-8 grid gap-8 lg:grid-cols-2">
        {/* ── Left column: Sources ──────────────────────────── */}
        <div className="space-y-8">
          {/* File Uploads */}
          <section>
            <div className="flex items-center gap-2">
              <Upload className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Documents
              </h2>
            </div>
            <div className="mt-3 space-y-3">
              <FileUploadZone onUploadComplete={refreshUploads} />
              <FileUploadList
                uploads={uploads.data ?? []}
                onDelete={(id) => deleteUploadMut.mutate(id)}
                isDeleting={deletingUpload}
              />
            </div>
          </section>

          {/* Website URL */}
          <section>
            <div className="flex items-center gap-2">
              <Globe className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Website
              </h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Enter your website URL to scrape content during pipeline processing.
            </p>
            <div className="mt-3 flex items-center gap-2">
              <input
                type="url"
                value={displayUrl}
                onChange={(e) => setWebsiteUrlInput(e.target.value)}
                placeholder="https://yourcompany.com"
                className="flex-1 rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <button
                onClick={() => saveWebsiteUrlMut.mutate(displayUrl)}
                disabled={saveWebsiteUrlMut.isPending || (websiteUrlInput === null)}
                className="inline-flex items-center gap-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
              >
                <Save className="h-3.5 w-3.5" />
                {saveWebsiteUrlMut.isPending ? "Saving..." : "Save"}
              </button>
            </div>
            {savedUrl && (
              <p className="mt-1.5 text-xs text-muted-foreground">
                Saved: {savedUrl}
              </p>
            )}
          </section>

          {/* Questionnaire */}
          <section>
            <div className="flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Questionnaire
              </h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Answer questions about your business to help Spark understand your
              voice, values, and customers.
            </p>
            <button
              onClick={() => setQuestionnaireOpen(true)}
              className="mt-3 inline-flex items-center gap-1.5 rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted"
            >
              <ClipboardList className="h-4 w-4" />
              Open Questionnaire
            </button>
            <QuestionnaireModal
              open={questionnaireOpen}
              onOpenChange={setQuestionnaireOpen}
            />
          </section>

          {/* Paste Area */}
          <section>
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Paste Content
              </h2>
            </div>
            <div className="mt-3 space-y-3">
              <PasteArea onSubmit={refreshPastes} />
              <PasteItemList
                items={pastes.data ?? []}
                onDelete={(id) => deletePasteMut.mutate(id)}
                isDeleting={deletingPaste}
              />
            </div>
          </section>
        </div>

        {/* ── Right column: Pipeline ───────────────────────── */}
        <div>
          <section>
            <div className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Pipeline
              </h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Process all your sources to generate profiles and knowledge base items.
            </p>

            {/* Scrape toggle */}
            <label className="mt-3 flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeScrape}
                onChange={(e) => setIncludeScrape(e.target.checked)}
                disabled={!savedUrl}
                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary disabled:opacity-50"
              />
              <span className="text-sm">
                Include website scrape
              </span>
              {!savedUrl && (
                <span className="text-xs text-muted-foreground">
                  (save a website URL first)
                </span>
              )}
            </label>

            <div className="mt-3">
              <PipelineStatus
                latestRun={latestRun}
                onTrigger={() => triggerPipeline.mutate()}
                onCancel={(id) => cancelPipeline.mutate(id)}
                isTriggerPending={triggerPipeline.isPending}
              />
            </div>
          </section>

          {/* Generated Profiles */}
          <section className="mt-8">
            <div className="flex items-center gap-2">
              <BookOpen className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Generated Profiles
              </h2>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              Profiles extracted from your source materials by the pipeline.
            </p>
            <div className="mt-3">
              <ProfileList
                profiles={profiles.data ?? []}
                onApprove={(id) => approveProfile.mutate(id)}
                onRequestChanges={(id, feedback) =>
                  requestProfileChanges.mutate({ id, feedback })
                }
                isUpdating={updatingProfile}
              />
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
