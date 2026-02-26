import { useEffect, useState, useCallback, createContext, useContext, type ReactNode } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

interface Toast {
  id: string;
  message: string;
  variant?: "default" | "destructive";
}

interface ToasterContextType {
  toast: (message: string, variant?: "default" | "destructive") => void;
}

const ToasterContext = createContext<ToasterContextType>({
  toast: () => {},
});

export function useToast() {
  return useContext(ToasterContext);
}

// Global toast function (usable outside React components)
let globalToast: ToasterContextType["toast"] = () => {};

export function toast(message: string, variant?: "default" | "destructive") {
  globalToast(message, variant);
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback(
    (message: string, variant: "default" | "destructive" = "default") => {
      const id = Math.random().toString(36).slice(2);
      setToasts((prev) => [...prev, { id, message, variant }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 5000);
    },
    []
  );

  useEffect(() => {
    globalToast = addToast;
  }, [addToast]);

  function dismiss(id: string) {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            "flex items-center gap-2 rounded-md border px-4 py-3 shadow-lg transition-all",
            t.variant === "destructive"
              ? "border-destructive/20 bg-destructive text-destructive-foreground"
              : "border-border bg-card text-foreground"
          )}
        >
          <span className="text-sm">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            className="ml-2 rounded-sm opacity-70 hover:opacity-100"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

export function ToasterProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
