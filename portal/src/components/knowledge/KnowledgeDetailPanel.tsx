import { useState, useEffect } from "react";
import { X, Trash2 } from "lucide-react";
import type {
  KnowledgeItem,
  KnowledgeUpdate,
  KnowledgeCategory,
} from "@/lib/types";
import { KNOWLEDGE_CATEGORY_LABELS } from "@/lib/types";
import { formatDate } from "@/lib/utils";

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

interface KnowledgeDetailPanelProps {
  item: KnowledgeItem;
  onClose: () => void;
  onSave: (id: string, update: KnowledgeUpdate) => void;
  onDelete: (id: string) => void;
}

export function KnowledgeDetailPanel({
  item,
  onClose,
  onSave,
  onDelete,
}: KnowledgeDetailPanelProps) {
  const [title, setTitle] = useState(item.title);
  const [content, setContent] = useState(item.content);
  const [category, setCategory] = useState<KnowledgeCategory>(item.category);
  const [subcategory, setSubcategory] = useState(item.subcategory || "");
  const [priority, setPriority] = useState(item.priority);
  const [active, setActive] = useState(item.active);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [dirty, setDirty] = useState(false);

  // Sync when item changes
  useEffect(() => {
    setTitle(item.title);
    setContent(item.content);
    setCategory(item.category);
    setSubcategory(item.subcategory || "");
    setPriority(item.priority);
    setActive(item.active);
    setDirty(false);
    setShowDeleteConfirm(false);
  }, [item.id]);

  function markDirty() {
    setDirty(true);
  }

  function handleSave() {
    const update: KnowledgeUpdate = {};
    if (title !== item.title) update.title = title;
    if (content !== item.content) update.content = content;
    if (category !== item.category) update.category = category;
    if (subcategory !== (item.subcategory || ""))
      update.subcategory = subcategory || undefined;
    if (priority !== item.priority) update.priority = priority;
    if (active !== item.active) update.active = active;

    if (Object.keys(update).length > 0) {
      onSave(item.id, update);
      setDirty(false);
    }
  }

  function handleDelete() {
    if (!showDeleteConfirm) {
      setShowDeleteConfirm(true);
      return;
    }
    onDelete(item.id);
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-lg overflow-y-auto border-l bg-card shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="font-medium">Knowledge Item</h2>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-5 p-4">
          {/* Title */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Title
            </label>
            <input
              value={title}
              onChange={(e) => {
                setTitle(e.target.value);
                markDirty();
              }}
              maxLength={200}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>

          {/* Content */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-muted-foreground">
              Content
            </label>
            <textarea
              value={content}
              onChange={(e) => {
                setContent(e.target.value);
                markDirty();
              }}
              rows={8}
              maxLength={3000}
              className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p className="text-xs text-muted-foreground">
              {content.length}/3000 characters
            </p>
          </div>

          {/* Category + Subcategory */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Category
              </label>
              <select
                value={category}
                onChange={(e) => {
                  setCategory(e.target.value as KnowledgeCategory);
                  markDirty();
                }}
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
                onChange={(e) => {
                  setSubcategory(e.target.value);
                  markDirty();
                }}
                placeholder="e.g. mission, pricing"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
          </div>

          {/* Priority + Active */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Priority (0–100)
              </label>
              <input
                type="number"
                value={priority}
                onChange={(e) => {
                  setPriority(
                    Math.max(0, Math.min(100, parseInt(e.target.value) || 0))
                  );
                  markDirty();
                }}
                min={0}
                max={100}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-muted-foreground">
                Status
              </label>
              <button
                onClick={() => {
                  setActive(!active);
                  markDirty();
                }}
                className={`h-9 w-full rounded-md border px-3 text-sm font-medium transition-colors ${
                  active
                    ? "border-green-300 bg-green-50 text-green-800"
                    : "border-gray-300 bg-gray-50 text-gray-600"
                }`}
              >
                {active ? "Active" : "Inactive"}
              </button>
            </div>
          </div>

          {/* Timestamps */}
          <div className="space-y-1 text-xs text-muted-foreground">
            <p>Created: {formatDate(item.created_at)}</p>
            <p>Updated: {formatDate(item.updated_at)}</p>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3 border-t pt-4">
            <button
              onClick={handleSave}
              disabled={!dirty}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
            >
              Save Changes
            </button>
            <button
              onClick={handleDelete}
              className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                showDeleteConfirm
                  ? "border-red-300 bg-red-50 text-red-700"
                  : "text-muted-foreground hover:text-red-600"
              }`}
            >
              <Trash2 className="h-4 w-4" />
              {showDeleteConfirm ? "Confirm Delete" : "Delete"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
