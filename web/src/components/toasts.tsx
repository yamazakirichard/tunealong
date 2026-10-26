import { createContext, type ReactNode, useCallback, useContext, useState } from "react";

export interface Toast {
  id: number;
  text: string;
  kind?: "info" | "error";
  action?: { label: string; run: () => void };
}

type Push = (t: Omit<Toast, "id">) => void;
const ToastContext = createContext<Push>(() => {});
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = (id: number) => setToasts((ts) => ts.filter((t) => t.id !== id));
  const push = useCallback<Push>((t) => {
    const id = nextId++;
    setToasts((ts) => [...ts, { ...t, id }]);
    setTimeout(() => dismiss(id), 8000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            data-testid="toast"
            className={`flex items-center gap-3 rounded-md px-4 py-2 text-sm shadow-lg ${
              t.kind === "error" ? "bg-red-700 text-white" : "bg-theme-700 text-theme-50 dark:bg-theme-200 dark:text-theme-900"
            }`}
          >
            <span>{t.text}</span>
            {t.action && (
              <button
                type="button"
                className="underline font-semibold"
                onClick={() => {
                  t.action!.run();
                  dismiss(t.id);
                }}
              >
                {t.action.label}
              </button>
            )}
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)} className="opacity-70">
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
