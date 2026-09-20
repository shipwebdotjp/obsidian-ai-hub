import { useCallback, useEffect, useRef, useState } from "react";

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "error";
}

/**
 * 一時通知の共通状態。`notify` で追加し、3.5 秒後に自動で消える。
 * 表示は `<ToastStack toasts={toasts} />` を描画する。
 */
export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef<number[]>([]);

  const notify = useCallback(
    (text: string, kind: "info" | "error" = "info") => {
      const id = ++idRef.current;
      setToasts((prev) => [...prev, { id, text, kind }]);
      const timer = window.setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
        timersRef.current = timersRef.current.filter((t) => t !== timer);
      }, 3500);
      timersRef.current.push(timer);
    },
    [],
  );

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => window.clearTimeout(timer));
      timersRef.current = [];
    };
  }, []);

  return { toasts, notify };
}

export function ToastStack({ toasts }: { toasts: Toast[] }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`pointer-events-auto rounded px-4 py-2 text-sm text-white shadow ${
            t.kind === "error" ? "bg-rose-600" : "bg-slate-900"
          }`}
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}
