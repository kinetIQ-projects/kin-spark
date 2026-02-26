import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Plus, Search } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type {
  KnowledgeItem,
  KnowledgeCreate,
  KnowledgeUpdate,
  KnowledgeStats,
  KnowledgeCategory,
  PaginatedResponse,
} from "@/lib/types";
import { KNOWLEDGE_CATEGORY_LABELS } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { Badge, KnowledgeCategoryBadge } from "@/components/common/Badge";
import { EmptyState } from "@/components/common/EmptyState";
import { Pagination } from "@/components/common/Pagination";
import { TableSkeleton } from "@/components/common/Skeleton";
import { ErrorCard } from "@/components/common/ErrorCard";
import { KnowledgeDetailPanel } from "@/components/knowledge/KnowledgeDetailPanel";
import { toast } from "@/components/ui/toaster";

const CATEGORIES: KnowledgeCategory[] = [
  "company",
  "product",
  "competitor",
  "legal",
  "team",
  "fun",
  "customer_profile",
  "procedure",
];

export function Knowledge() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [category, setCategory] = useState("");
  const [activeFilter, setActiveFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [selectedItem, setSelectedItem] = useState<KnowledgeItem | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout>>();
  const limit = 50;

  // Debounce search
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => {
      setDebouncedSearch(search);
      setOffset(0);
    }, 300);
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    };
  }, [search]);

  // Build query params
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (category) params.set("category", category);
  if (activeFilter) params.set("active", activeFilter);
  if (debouncedSearch) params.set("search", debouncedSearch);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["knowledge", offset, category, activeFilter, debouncedSearch],
    queryFn: () =>
      apiFetch<PaginatedResponse<KnowledgeItem>>(
        `/knowledge?${params.toString()}`
      ),
    refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ["knowledge-stats"],
    queryFn: () => apiFetch<KnowledgeStats>("/knowledge/stats"),
    refetchInterval: 60_000,
  });

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (body: KnowledgeCreate) =>
      apiFetch<KnowledgeItem>("/knowledge", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: (item) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
      setShowCreate(false);
      setSelectedItem(item);
      toast("Knowledge item created", "default");
    },
    onError: (err) => {
      const msg =
        err instanceof Error ? err.message : "Failed to create item";
      toast(msg, "destructive");
    },
  });

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({ id, update }: { id: string; update: KnowledgeUpdate }) =>
      apiFetch<KnowledgeItem>(`/knowledge/${id}`, {
        method: "PATCH",
        body: JSON.stringify(update),
      }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
      setSelectedItem(updated);
      toast("Knowledge item updated", "default");
    },
    onError: (err) => {
      const msg =
        err instanceof Error ? err.message : "Failed to update item";
      toast(msg, "destructive");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiFetch<void>(`/knowledge/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-stats"] });
      setSelectedItem(null);
      toast("Knowledge item deleted", "default");
    },
    onError: () => {
      toast("Failed to delete item", "destructive");
    },
  });

  const handleSave = useCallback(
    (id: string, update: KnowledgeUpdate) => {
      updateMutation.mutate({ id, update });
    },
    [updateMutation]
  );

  const handleDelete = useCallback(
    (id: string) => {
      deleteMutation.mutate(id);
    },
    [deleteMutation]
  );

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            Knowledge Base
          </h1>
          {stats && (
            <div className="flex items-center gap-2">
              <Badge variant="blue">{stats.total_items} items</Badge>
              <Badge variant="green">{stats.active_items} active</Badge>
            </div>
          )}
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          Add Item
        </button>
      </div>

      {/* Filters */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <select
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {KNOWLEDGE_CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>

        <select
          value={activeFilter}
          onChange={(e) => {
            setActiveFilter(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          <option value="">All items</option>
          <option value="true">Active only</option>
          <option value="false">Inactive only</option>
        </select>

        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search titles..."
            className="h-9 rounded-md border bg-background pl-8 pr-3 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>

      {/* Table */}
      <div className="mt-4 rounded-lg border">
        {isLoading ? (
          <div className="py-4">
            <TableSkeleton rows={8} />
          </div>
        ) : isError ? (
          <div className="p-4">
            <ErrorCard
              message="Failed to load knowledge items"
              onRetry={() => refetch()}
            />
          </div>
        ) : !data?.items.length ? (
          <EmptyState
            icon={BookOpen}
            title="No knowledge items"
            description="Add your first knowledge item to train your AI rep."
          />
        ) : (
          <>
            {/* Header */}
            <div className="hidden border-b bg-muted/50 px-4 py-2 text-xs font-medium text-muted-foreground md:grid md:grid-cols-[2fr_1fr_1fr_60px_60px_100px]">
              <span>Title</span>
              <span>Category</span>
              <span>Subcategory</span>
              <span>Priority</span>
              <span>Active</span>
              <span>Updated</span>
            </div>

            {/* Rows */}
            {data.items.map((item) => (
              <div
                key={item.id}
                onClick={() => setSelectedItem(item)}
                className="cursor-pointer border-b px-4 py-3 transition-colors last:border-b-0 hover:bg-muted/50 md:grid md:grid-cols-[2fr_1fr_1fr_60px_60px_100px] md:items-center"
              >
                <span className="text-sm font-medium">{item.title}</span>
                <div>
                  <KnowledgeCategoryBadge category={item.category} />
                </div>
                <span className="text-sm text-muted-foreground">
                  {item.subcategory || "—"}
                </span>
                <span className="text-sm text-muted-foreground">
                  {item.priority}
                </span>
                <span>
                  <span
                    className={`inline-block h-2 w-2 rounded-full ${
                      item.active ? "bg-green-500" : "bg-gray-300"
                    }`}
                  />
                </span>
                <span className="text-sm text-muted-foreground">
                  {formatDate(item.updated_at)}
                </span>
              </div>
            ))}

            <Pagination
              total={data.total}
              limit={limit}
              offset={offset}
              onOffsetChange={setOffset}
            />
          </>
        )}
      </div>

      {/* Detail Panel */}
      {selectedItem && !showCreate && (
        <KnowledgeDetailPanel
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
          onSave={handleSave}
          onDelete={handleDelete}
        />
      )}

      {/* Create Modal */}
      {showCreate && (
        <CreateKnowledgeModal
          onClose={() => setShowCreate(false)}
          onCreate={(body) => createMutation.mutate(body)}
          isLoading={createMutation.isPending}
        />
      )}
    </div>
  );
}

// ── Create Modal ────────────────────────────────────────────────

interface CreateKnowledgeModalProps {
  onClose: () => void;
  onCreate: (body: KnowledgeCreate) => void;
  isLoading: boolean;
}

function CreateKnowledgeModal({
  onClose,
  onCreate,
  isLoading,
}: CreateKnowledgeModalProps) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<KnowledgeCategory>("company");
  const [subcategory, setSubcategory] = useState("");
  const [priority, setPriority] = useState(0);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !content.trim()) return;
    onCreate({
      title: title.trim(),
      content: content.trim(),
      category,
      subcategory: subcategory.trim() || undefined,
      priority,
      active: true,
    });
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-y-auto border-l bg-card shadow-xl">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="font-medium">New Knowledge Item</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground"
          >
            <span className="text-lg">&times;</span>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5 p-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Title *
            </label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={200}
              required
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Content *
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={8}
              maxLength={3000}
              required
              placeholder="The knowledge your AI rep should know..."
              className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground">
              {content.length}/3000 characters
            </p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Category
              </label>
              <select
                value={category}
                onChange={(e) =>
                  setCategory(e.target.value as KnowledgeCategory)
                }
                className="h-9 w-full rounded-md border bg-background px-3 text-sm"
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {KNOWLEDGE_CATEGORY_LABELS[c]}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Subcategory
              </label>
              <input
                value={subcategory}
                onChange={(e) => setSubcategory(e.target.value)}
                placeholder="e.g. mission, pricing"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Priority (0–100)
            </label>
            <input
              type="number"
              value={priority}
              onChange={(e) =>
                setPriority(
                  Math.max(0, Math.min(100, parseInt(e.target.value) || 0))
                )
              }
              min={0}
              max={100}
              className="w-32 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          <div className="flex items-center gap-3 border-t pt-4">
            <button
              type="submit"
              disabled={isLoading || !title.trim() || !content.trim()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
            >
              {isLoading ? "Creating..." : "Create Item"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </>
  );
}
