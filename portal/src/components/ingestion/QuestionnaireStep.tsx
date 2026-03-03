interface QuestionnaireStepProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  inputType?: "text" | "textarea";
}

export function QuestionnaireStep({
  label,
  value,
  onChange,
  inputType = "textarea",
}: QuestionnaireStepProps) {
  return (
    <div className="space-y-3">
      <label className="text-sm font-medium">{label}</label>
      {inputType === "textarea" ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={5}
          className="w-full resize-y rounded-md border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          autoFocus
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          autoFocus
        />
      )}
    </div>
  );
}
