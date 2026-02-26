import { useState, useRef, useCallback, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ClipboardList,
  ChevronDown,
  Check,
  Circle,
  Plus,
  Trash2,
  Save,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { OnboardingData, OnboardingCustomerProfile } from "@/lib/types";
import { formatDate } from "@/lib/utils";
import { toast } from "@/components/ui/toaster";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorCard } from "@/components/common/ErrorCard";
import { cn } from "@/lib/utils";

// ── API helpers ─────────────────────────────────────────────────

function fetchOnboarding(): Promise<{ onboarding_data: OnboardingData }> {
  return apiFetch<{ onboarding_data: OnboardingData }>("/onboarding");
}

function updateOnboarding(
  data: Partial<OnboardingData>
): Promise<{ onboarding_data: OnboardingData }> {
  return apiFetch<{ onboarding_data: OnboardingData }>("/onboarding", {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ── Section definitions ─────────────────────────────────────────

interface FieldDef {
  key: string;
  label: string;
}

interface SectionDef {
  id: string;
  title: string;
  dataKey: keyof OnboardingData;
  fields: FieldDef[];
}

const SECTIONS: SectionDef[] = [
  {
    id: "purpose_story",
    title: "Purpose & Story",
    dataKey: "purpose_story",
    fields: [
      {
        key: "a1_why_started",
        label:
          "Why did you start this company? What problem were you trying to solve?",
      },
      {
        key: "a2_what_would_lose",
        label:
          "What would the world lose if your company disappeared tomorrow?",
      },
      {
        key: "a3_one_sentence",
        label:
          "In one sentence: what do you do and who do you do it for?",
      },
      {
        key: "a4_future_vision",
        label: "Where do you see this company in 3 years?",
      },
    ],
  },
  {
    id: "values_culture",
    title: "Values & Culture",
    dataKey: "values_culture",
    fields: [
      {
        key: "b1_team_cares_about",
        label: "What does your team care about most deeply?",
      },
      {
        key: "b2_tradeoff_example",
        label:
          "Tell me about a time you made a hard tradeoff that showed what your company really values.",
      },
      {
        key: "b3_unusual_thing",
        label:
          "What's something unusual about how you operate that most companies don't do?",
      },
      {
        key: "b4_never_experience",
        label:
          "What should a customer never experience when working with you?",
      },
    ],
  },
  {
    id: "brand_voice",
    title: "Brand Voice",
    dataKey: "brand_voice",
    fields: [
      {
        key: "c1_brand_at_party",
        label:
          "If your brand walked into a party, who would it be? How would it talk?",
      },
      {
        key: "c2_three_feeling_words",
        label:
          "What three words do you want people to feel after interacting with you?",
      },
      {
        key: "c3_voice_model",
        label:
          "Whose voice or writing style is closest to yours?",
      },
      {
        key: "c4_anti_voice",
        label:
          "What does 'not you' sound like? Give an example of messaging that makes you cringe.",
      },
      {
        key: "c5_writing_samples",
        label:
          "Paste any writing samples, emails, or social posts that sound like you.",
      },
    ],
  },
  {
    id: "procedures_policies",
    title: "Procedures & Policies",
    dataKey: "procedures_policies",
    fields: [
      {
        key: "e1_top_questions",
        label: "What are the top 5 questions your customers ask?",
      },
      {
        key: "e2_unhappy_process",
        label:
          "What happens when a customer is unhappy? Walk us through your process.",
      },
      {
        key: "e3_human_handoff",
        label:
          "When should Spark hand off to a human? What are the triggers?",
      },
      {
        key: "e4_legal_compliance",
        label:
          "Any legal or compliance requirements Spark needs to know about?",
      },
    ],
  },
];

// ── Helpers ──────────────────────────────────────────────────────

function isSectionComplete(
  sectionDef: SectionDef,
  data: OnboardingData | undefined
): boolean {
  if (!data) return false;
  const sectionData = data[sectionDef.dataKey];
  if (!sectionData || typeof sectionData !== "object" || Array.isArray(sectionData))
    return false;
  const record = sectionData as Record<string, string | string[]>;
  return sectionDef.fields.every((f) => {
    const val = record[f.key];
    if (Array.isArray(val)) return val.length > 0 && val.some((v) => v.trim() !== "");
    return typeof val === "string" && val.trim() !== "";
  });
}

function isCustomersComplete(data: OnboardingData | undefined): boolean {
  if (!data || !data.customers || data.customers.length === 0) return false;
  return data.customers.every(
    (c) =>
      c.name.trim() !== "" &&
      c.description.trim() !== "" &&
      c.signals.trim() !== "" &&
      c.needs.trim() !== ""
  );
}

function isAdditionalContextComplete(data: OnboardingData | undefined): boolean {
  if (!data) return false;
  return typeof data.additional_context === "string" && data.additional_context.trim() !== "";
}

const EMPTY_CUSTOMER: OnboardingCustomerProfile = {
  name: "",
  description: "",
  signals: "",
  needs: "",
};

// ── Main component ──────────────────────────────────────────────

export function Onboarding() {
  const queryClient = useQueryClient();

  // ── Local form state ──────────────────────────────────────────
  const [formData, setFormData] = useState<OnboardingData | null>(null);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const debounceTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  // ── Query ─────────────────────────────────────────────────────
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["onboarding"],
    queryFn: fetchOnboarding,
  });

  // Sync server data into local form state on load
  useEffect(() => {
    if (data?.onboarding_data && !formData) {
      const serverData = data.onboarding_data;
      // Ensure customers has at least one empty profile
      if (!serverData.customers || serverData.customers.length === 0) {
        serverData.customers = [{ name: "", description: "", signals: "", needs: "" }];
      }
      setFormData(serverData);
    }
  }, [data, formData]);

  // ── Mutation ──────────────────────────────────────────────────
  const saveMutation = useMutation({
    mutationFn: updateOnboarding,
    onSuccess: (result) => {
      queryClient.setQueryData(["onboarding"], result);
      // Keep local state in sync with server response
      setFormData(result.onboarding_data);
      toast("Saved");
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Failed to save";
      toast(msg, "destructive");
    },
  });

  // ── Section field change with debounced auto-save ─────────────
  const handleSectionFieldChange = useCallback(
    (sectionKey: string, fieldKey: string, value: string) => {
      setFormData((prev) => {
        if (!prev) return prev;
        const section = (prev[sectionKey as keyof OnboardingData] ?? {}) as Record<
          string,
          string | string[]
        >;
        return {
          ...prev,
          [sectionKey]: { ...section, [fieldKey]: value },
        };
      });

      // Debounced auto-save for the entire section
      const timerKey = sectionKey;
      if (debounceTimers.current[timerKey]) {
        clearTimeout(debounceTimers.current[timerKey]);
      }
      debounceTimers.current[timerKey] = setTimeout(() => {
        setFormData((current) => {
          if (current) {
            saveMutation.mutate({
              [sectionKey]: current[sectionKey as keyof OnboardingData],
            });
          }
          return current;
        });
      }, 2000);
    },
    [saveMutation]
  );

  // ── Customer profile changes with debounced auto-save ─────────
  const handleCustomerChange = useCallback(
    (index: number, field: keyof OnboardingCustomerProfile, value: string) => {
      setFormData((prev) => {
        if (!prev) return prev;
        const customers = [...prev.customers];
        customers[index] = { ...customers[index]!, [field]: value };
        return { ...prev, customers };
      });

      const timerKey = "customers";
      if (debounceTimers.current[timerKey]) {
        clearTimeout(debounceTimers.current[timerKey]);
      }
      debounceTimers.current[timerKey] = setTimeout(() => {
        setFormData((current) => {
          if (current) {
            saveMutation.mutate({ customers: current.customers });
          }
          return current;
        });
      }, 2000);
    },
    [saveMutation]
  );

  const addCustomerProfile = useCallback(() => {
    setFormData((prev) => {
      if (!prev) return prev;
      return { ...prev, customers: [...prev.customers, { ...EMPTY_CUSTOMER }] };
    });
  }, []);

  const removeCustomerProfile = useCallback(
    (index: number) => {
      setFormData((prev) => {
        if (!prev) return prev;
        const customers = prev.customers.filter((_, i) => i !== index);
        // Auto-save after removal
        setTimeout(() => {
          saveMutation.mutate({ customers });
        }, 0);
        return { ...prev, customers };
      });
    },
    [saveMutation]
  );

  // ── Additional context change with debounced auto-save ────────
  const handleAdditionalContextChange = useCallback(
    (value: string) => {
      setFormData((prev) => {
        if (!prev) return prev;
        return { ...prev, additional_context: value };
      });

      const timerKey = "additional_context";
      if (debounceTimers.current[timerKey]) {
        clearTimeout(debounceTimers.current[timerKey]);
      }
      debounceTimers.current[timerKey] = setTimeout(() => {
        setFormData((current) => {
          if (current) {
            saveMutation.mutate({ additional_context: current.additional_context });
          }
          return current;
        });
      }, 2000);
    },
    [saveMutation]
  );

  // ── Save all ──────────────────────────────────────────────────
  const handleSaveAll = useCallback(() => {
    if (!formData) return;
    // Clear any pending debounce timers
    Object.values(debounceTimers.current).forEach(clearTimeout);
    debounceTimers.current = {};
    saveMutation.mutate(formData);
  }, [formData, saveMutation]);

  // ── Mark complete ─────────────────────────────────────────────
  const handleMarkComplete = useCallback(() => {
    if (!formData) return;
    // Clear any pending debounce timers
    Object.values(debounceTimers.current).forEach(clearTimeout);
    debounceTimers.current = {};
    saveMutation.mutate({
      ...formData,
      completed_at: new Date().toISOString(),
    });
  }, [formData, saveMutation]);

  // ── Toggle section collapse ───────────────────────────────────
  const toggleCollapse = useCallback((sectionId: string) => {
    setCollapsed((prev) => ({ ...prev, [sectionId]: !prev[sectionId] }));
  }, []);

  // ── Loading / Error states ────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="mt-8">
        <ErrorCard
          message="Failed to load onboarding data"
          onRetry={() => refetch()}
        />
      </div>
    );
  }

  if (!formData) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  // Customers guaranteed to have at least one profile from useEffect init
  const customers = formData.customers;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            Onboarding
          </h1>
          {formData.completed_at && (
            <span className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
              <Check className="h-3 w-3" />
              Completed
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {formData.last_saved_at && (
            <span className="text-xs text-muted-foreground">
              Last saved: {formatDate(formData.last_saved_at)}
            </span>
          )}
          <button
            onClick={handleSaveAll}
            disabled={saveMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
          >
            <Save className="h-4 w-4" />
            {saveMutation.isPending ? "Saving..." : "Save All"}
          </button>
        </div>
      </div>

      <p className="mt-2 text-sm text-muted-foreground">
        Tell us about your business so Spark can represent you authentically.
        Your answers auto-save as you type.
      </p>

      {/* Sections */}
      <div className="mt-6 space-y-4">
        {/* Standard record sections */}
        {SECTIONS.map((section) => {
          const complete = isSectionComplete(section, formData);
          const isCollapsed = collapsed[section.id] ?? false;
          const sectionData = (formData[section.dataKey] ?? {}) as Record<
            string,
            string | string[]
          >;

          return (
            <div key={section.id} className="rounded-lg border">
              <button
                type="button"
                onClick={() => toggleCollapse(section.id)}
                className="flex w-full items-center justify-between px-5 py-4 text-left"
              >
                <div className="flex items-center gap-3">
                  {complete ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium">{section.title}</span>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    isCollapsed && "-rotate-90"
                  )}
                />
              </button>
              {!isCollapsed && (
                <div className="space-y-5 border-t px-5 py-5">
                  {section.fields.map((field) => {
                    const val = sectionData[field.key];
                    const strVal = Array.isArray(val) ? val.join("\n") : (val ?? "");
                    return (
                      <div key={field.key} className="space-y-1.5">
                        <label className="text-sm font-medium text-muted-foreground">
                          {field.label}
                        </label>
                        <textarea
                          value={strVal}
                          onChange={(e) =>
                            handleSectionFieldChange(
                              section.dataKey,
                              field.key,
                              e.target.value
                            )
                          }
                          rows={3}
                          className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}

        {/* Customers section */}
        {(() => {
          const customersComplete = isCustomersComplete(formData);
          const isCollapsed = collapsed["customers"] ?? false;

          return (
            <div className="rounded-lg border">
              <button
                type="button"
                onClick={() => toggleCollapse("customers")}
                className="flex w-full items-center justify-between px-5 py-4 text-left"
              >
                <div className="flex items-center gap-3">
                  {customersComplete ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium">Customers</span>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    isCollapsed && "-rotate-90"
                  )}
                />
              </button>
              {!isCollapsed && (
                <div className="space-y-6 border-t px-5 py-5">
                  {customers.map((customer, idx) => (
                    <div
                      key={idx}
                      className="space-y-4 rounded-md border bg-muted/20 p-4"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium">
                          Customer Profile {idx + 1}
                        </span>
                        {customers.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeCustomerProfile(idx)}
                            className="inline-flex items-center gap-1 rounded-md p-1 text-sm text-muted-foreground transition-colors hover:text-destructive"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-muted-foreground">
                          Customer type (e.g., &quot;Enterprise Buyer&quot;,
                          &quot;Small Business Owner&quot;)
                        </label>
                        <input
                          type="text"
                          value={customer.name}
                          onChange={(e) =>
                            handleCustomerChange(idx, "name", e.target.value)
                          }
                          className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-muted-foreground">
                          Describe this customer type
                        </label>
                        <textarea
                          value={customer.description}
                          onChange={(e) =>
                            handleCustomerChange(
                              idx,
                              "description",
                              e.target.value
                            )
                          }
                          rows={3}
                          className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-muted-foreground">
                          How do you recognize them? What do they say or ask?
                        </label>
                        <textarea
                          value={customer.signals}
                          onChange={(e) =>
                            handleCustomerChange(idx, "signals", e.target.value)
                          }
                          rows={3}
                          className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>

                      <div className="space-y-1.5">
                        <label className="text-sm font-medium text-muted-foreground">
                          What do they need most from you?
                        </label>
                        <textarea
                          value={customer.needs}
                          onChange={(e) =>
                            handleCustomerChange(idx, "needs", e.target.value)
                          }
                          rows={3}
                          className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        />
                      </div>
                    </div>
                  ))}

                  <button
                    type="button"
                    onClick={addCustomerProfile}
                    className="inline-flex items-center gap-1.5 rounded-md border border-dashed px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <Plus className="h-4 w-4" />
                    Add Customer Profile
                  </button>
                </div>
              )}
            </div>
          );
        })()}

        {/* Additional Context section */}
        {(() => {
          const contextComplete = isAdditionalContextComplete(formData);
          const isCollapsed = collapsed["additional_context"] ?? false;
          const contextValue = formData.additional_context ?? "";

          return (
            <div className="rounded-lg border">
              <button
                type="button"
                onClick={() => toggleCollapse("additional_context")}
                className="flex w-full items-center justify-between px-5 py-4 text-left"
              >
                <div className="flex items-center gap-3">
                  {contextComplete ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Circle className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium">
                    Additional Context
                  </span>
                </div>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 text-muted-foreground transition-transform",
                    isCollapsed && "-rotate-90"
                  )}
                />
              </button>
              {!isCollapsed && (
                <div className="space-y-1.5 border-t px-5 py-5">
                  <label className="text-sm font-medium text-muted-foreground">
                    Anything else Spark should know about your business?
                  </label>
                  <textarea
                    value={contextValue}
                    onChange={(e) => {
                      if (e.target.value.length <= 5000) {
                        handleAdditionalContextChange(e.target.value);
                      }
                    }}
                    rows={5}
                    maxLength={5000}
                    className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  />
                  <p className="text-xs text-muted-foreground">
                    {contextValue.length}/5000 characters
                  </p>
                </div>
              )}
            </div>
          );
        })()}
      </div>

      {/* Footer actions */}
      <div className="mt-8 flex items-center gap-3 border-t pt-6">
        <button
          onClick={handleSaveAll}
          disabled={saveMutation.isPending}
          className="inline-flex items-center gap-1.5 rounded-md border px-4 py-2 text-sm font-medium transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
        >
          <Save className="h-4 w-4" />
          {saveMutation.isPending ? "Saving..." : "Save All"}
        </button>
        <button
          onClick={handleMarkComplete}
          disabled={saveMutation.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
        >
          <ClipboardList className="h-4 w-4" />
          {saveMutation.isPending ? "Saving..." : "Mark Complete"}
        </button>
        {formData.completed_at && (
          <span className="text-xs text-muted-foreground">
            Completed: {formatDate(formData.completed_at)}
          </span>
        )}
      </div>
    </div>
  );
}
