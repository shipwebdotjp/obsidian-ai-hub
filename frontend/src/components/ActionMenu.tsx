import { useEffect, useRef, useState } from "react";

export interface ActionMenuItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  tone?: "default" | "danger";
  testId?: string;
}

interface ActionMenuProps {
  /** Accessible name of the trigger (defaults to "⋯" glyph display). */
  label?: string;
  items: ActionMenuItem[];
  disabled?: boolean;
  testId?: string;
}

/**
 * Lightweight dropdown menu. Closes on outside click, Escape, or item
 * selection. Keep labels short; destructive items use `tone: "danger"`.
 */
export function ActionMenu({ label = "その他の操作", items, disabled = false, testId }: ActionMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.isComposing) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        aria-expanded={open}
        aria-label={label}
        data-testid={testId}
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
        className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        ⋯
      </button>
      {open && (
        <div
          className="absolute right-0 z-30 mt-1 min-w-44 rounded border border-slate-200 bg-white py-1 shadow-lg"
        >
          {items.map((item, index) => (
            <button
              key={item.testId ?? `${item.label}-${index}`}
              type="button"
              disabled={item.disabled}
              data-testid={item.testId}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`block w-full cursor-pointer px-3 py-1.5 text-left text-xs disabled:cursor-not-allowed disabled:opacity-50 ${
                item.tone === "danger"
                  ? "text-rose-700 hover:bg-rose-50"
                  : "text-slate-700 hover:bg-slate-100"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
