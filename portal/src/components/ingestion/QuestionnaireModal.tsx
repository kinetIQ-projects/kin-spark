import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { X, ChevronLeft, ChevronRight, SkipForward, Check } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import { apiFetch } from "@/lib/api";
import { toast } from "@/components/ui/toaster";
import { QuestionnaireStep } from "./QuestionnaireStep";
import type { OnboardingData, OnboardingCustomerProfile } from "@/lib/types";

// ── Flat question list ────────────────────────────────────────────

interface FlatQuestion {
  sectionKey: string;
  fieldKey: string;
  label: string;
}

const QUESTIONS: FlatQuestion[] = [
  // Purpose & Story
  { sectionKey: "purpose_story", fieldKey: "a1_why_started", label: "Why did you start this company? What problem were you trying to solve?" },
  { sectionKey: "purpose_story", fieldKey: "a2_what_would_lose", label: "What would the world lose if your company disappeared tomorrow?" },
  { sectionKey: "purpose_story", fieldKey: "a3_one_sentence", label: "In one sentence: what do you do and who do you do it for?" },
  { sectionKey: "purpose_story", fieldKey: "a4_future_vision", label: "Where do you see this company in 3 years?" },
  // Values & Culture
  { sectionKey: "values_culture", fieldKey: "b1_team_cares_about", label: "What does your team care about most deeply?" },
  { sectionKey: "values_culture", fieldKey: "b2_tradeoff_example", label: "Tell me about a time you made a hard tradeoff that showed what your company really values." },
  { sectionKey: "values_culture", fieldKey: "b3_unusual_thing", label: "What's something unusual about how you operate that most companies don't do?" },
  { sectionKey: "values_culture", fieldKey: "b4_never_experience", label: "What should a customer never experience when working with you?" },
  // Brand Voice
  { sectionKey: "brand_voice", fieldKey: "c1_brand_at_party", label: "If your brand walked into a party, who would it be? How would it talk?" },
  { sectionKey: "brand_voice", fieldKey: "c2_three_feeling_words", label: "What three words do you want people to feel after interacting with you?" },
  { sectionKey: "brand_voice", fieldKey: "c3_voice_model", label: "Whose voice or writing style is closest to yours?" },
  { sectionKey: "brand_voice", fieldKey: "c4_anti_voice", label: "What does 'not you' sound like? Give an example of messaging that makes you cringe." },
  { sectionKey: "brand_voice", fieldKey: "c5_writing_samples", label: "Paste any writing samples, emails, or social posts that sound like you." },
  // Procedures & Policies
  { sectionKey: "procedures_policies", fieldKey: "e1_top_questions", label: "What are the top 5 questions your customers ask?" },
  { sectionKey: "procedures_policies", fieldKey: "e2_unhappy_process", label: "What happens when a customer is unhappy? Walk us through your process." },
  { sectionKey: "procedures_policies", fieldKey: "e3_human_handoff", label: "When should Spark hand off to a human? What are the triggers?" },
  { sectionKey: "procedures_policies", fieldKey: "e4_legal_compliance", label: "Any legal or compliance requirements Spark needs to know about?" },
];

const TOTAL_QUESTIONS = QUESTIONS.length;

// ── Component ─────────────────────────────────────────────────────

interface QuestionnaireModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function QuestionnaireModal({
  open,
  onOpenChange,
}: QuestionnaireModalProps) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [formData, setFormData] = useState<OnboardingData | null>(null);

  // Fetch current data
  const { data } = useQuery({
    queryKey: ["onboarding"],
    queryFn: () =>
      apiFetch<{ onboarding_data: OnboardingData }>("/onboarding"),
    enabled: open,
  });

  // Sync on open
  useEffect(() => {
    if (open && data?.onboarding_data) {
      setFormData(data.onboarding_data);
      // Find first unanswered question
      const idx = QUESTIONS.findIndex((q) => {
        const section = (data.onboarding_data[
          q.sectionKey as keyof OnboardingData
        ] ?? {}) as Record<string, string>;
        const val = section[q.fieldKey];
        return !val || (typeof val === "string" && val.trim() === "");
      });
      setStep(idx >= 0 ? idx : 0);
    }
  }, [open, data]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (updates: Partial<OnboardingData>) =>
      apiFetch<{ onboarding_data: OnboardingData }>("/onboarding", {
        method: "PATCH",
        body: JSON.stringify(updates),
      }),
    onSuccess: (result) => {
      queryClient.setQueryData(["onboarding"], result);
    },
    onError: () => {
      toast("Failed to save", "destructive");
    },
  });

  // Save current step's section
  const saveCurrentStep = useCallback(() => {
    if (!formData) return;
    const q = QUESTIONS[step];
    if (!q) return;
    const sectionData = formData[q.sectionKey as keyof OnboardingData];
    saveMutation.mutate({ [q.sectionKey]: sectionData });
  }, [formData, step, saveMutation]);

  // Get current value
  const currentQuestion = QUESTIONS[step];
  const currentValue = (() => {
    if (!formData || !currentQuestion) return "";
    const section = (formData[
      currentQuestion.sectionKey as keyof OnboardingData
    ] ?? {}) as Record<string, string | string[]>;
    const val = section[currentQuestion.fieldKey];
    if (Array.isArray(val)) return val.join("\n");
    return (val as string) ?? "";
  })();

  // Update value
  const handleChange = useCallback(
    (value: string) => {
      if (!formData || !currentQuestion) return;
      const section = (formData[
        currentQuestion.sectionKey as keyof OnboardingData
      ] ?? {}) as Record<string, string | string[]>;
      setFormData({
        ...formData,
        [currentQuestion.sectionKey]: {
          ...section,
          [currentQuestion.fieldKey]: value,
        },
      });
    },
    [formData, currentQuestion]
  );

  const goNext = useCallback(() => {
    saveCurrentStep();
    if (step < TOTAL_QUESTIONS - 1) {
      setStep(step + 1);
    } else {
      // All done — mark complete
      if (formData) {
        saveMutation.mutate({
          ...formData,
          completed_at: new Date().toISOString(),
        });
      }
      toast("Questionnaire complete");
      onOpenChange(false);
    }
  }, [step, saveCurrentStep, formData, saveMutation, onOpenChange]);

  const goBack = useCallback(() => {
    saveCurrentStep();
    if (step > 0) setStep(step - 1);
  }, [step, saveCurrentStep]);

  const skip = useCallback(() => {
    saveCurrentStep();
    if (step < TOTAL_QUESTIONS - 1) {
      setStep(step + 1);
    }
  }, [step, saveCurrentStep]);

  if (!formData) return null;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border bg-background p-6 shadow-lg">
          {/* Header */}
          <div className="flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold">
              Questionnaire
            </Dialog.Title>
            <Dialog.Close asChild>
              <button className="rounded-md p-1 text-muted-foreground hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>

          {/* Progress */}
          <div className="mt-3 flex items-center gap-2">
            <div className="h-1.5 flex-1 rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{
                  width: `${((step + 1) / TOTAL_QUESTIONS) * 100}%`,
                }}
              />
            </div>
            <span className="text-xs text-muted-foreground">
              {step + 1} of {TOTAL_QUESTIONS}
            </span>
          </div>

          {/* Question */}
          <div className="mt-5">
            {currentQuestion && (
              <QuestionnaireStep
                label={currentQuestion.label}
                value={currentValue}
                onChange={handleChange}
              />
            )}
          </div>

          {/* Navigation */}
          <div className="mt-6 flex items-center justify-between">
            <button
              onClick={goBack}
              disabled={step === 0}
              className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
            >
              <ChevronLeft className="h-4 w-4" />
              Back
            </button>

            <div className="flex items-center gap-2">
              <button
                onClick={skip}
                disabled={step >= TOTAL_QUESTIONS - 1}
                className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
              >
                <SkipForward className="h-3.5 w-3.5" />
                Skip
              </button>
              <button
                onClick={goNext}
                disabled={saveMutation.isPending}
                className="inline-flex items-center gap-1 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:opacity-50"
              >
                {step >= TOTAL_QUESTIONS - 1 ? (
                  <>
                    <Check className="h-4 w-4" />
                    Finish
                  </>
                ) : (
                  <>
                    Next
                    <ChevronRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
