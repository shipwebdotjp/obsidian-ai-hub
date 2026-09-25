import { useRef, useState } from "react";
import type { WorkflowSchemaField } from "../../api/types";
import {
  completionCandidates,
  forLoopBindings,
  tokenAt,
  type CompletionCandidate,
  type TemplateVariable,
} from "./textTemplateModel";

export interface TextTemplateEditorProps {
  value: string;
  onChange: (value: string) => void;
  variables: TemplateVariable[];
  /** Resolve a variable or loop-iterable name to its declared JSON schema. */
  schemaFor: (name: string) => WorkflowSchemaField | null;
  testIdPrefix?: string;
}

/**
 * ``text_template`` body editor: a plain textarea augmented with ``{{ }}``
 * variable completion and nested field completion for ``{% for %}`` bindings.
 *
 * Completion is intentionally lightweight (no code-editor dependency) and
 * regex-based; it covers single-variable ``{% for X in Y %}`` loops.
 */
export default function TextTemplateEditor({
  value,
  onChange,
  variables,
  schemaFor,
  testIdPrefix = "text-template",
}: TextTemplateEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [candidates, setCandidates] = useState<CompletionCandidate[]>([]);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(0);

  const refreshCompletion = (nextValue: string, caret: number) => {
    const nextToken = tokenAt(nextValue, caret);
    if (!nextToken) {
      setOpen(false);
      setCandidates([]);
      return;
    }
    const next = completionCandidates(
      nextToken,
      variables,
      forLoopBindings(nextValue),
      schemaFor,
    );
    setCandidates(next);
    setSelected(0);
    setOpen(next.length > 0);
  };

  const insertText = (text: string) => {
    const el = textareaRef.current;
    const start = el?.selectionStart ?? value.length;
    const end = el?.selectionEnd ?? start;
    const next = value.slice(0, start) + text + value.slice(end);
    onChange(next);
    const nextCaret = start + text.length;
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const applyCandidate = (candidate: CompletionCandidate) => {
    const el = textareaRef.current;
    if (!el) return;
    // Recompute the token from the live caret: the selection may have moved
    // since the list was built, and the stored offsets would corrupt the text.
    const caret = el.selectionStart;
    const current = tokenAt(value, caret);
    if (!current) return;
    const next =
      value.slice(0, current.start) + candidate.value + value.slice(caret);
    onChange(next);
    const nextCaret = current.start + candidate.value.length;
    setOpen(false);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(nextCaret, nextCaret);
    });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Never intercept keys that are confirming an IME composition.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === " " && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      refreshCompletion(value, event.currentTarget.selectionStart);
      return;
    }
    if (!open || candidates.length === 0) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setSelected((current) => (current + 1) % candidates.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setSelected(
        (current) => (current - 1 + candidates.length) % candidates.length,
      );
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      applyCandidate(candidates[selected]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div className="space-y-1">
      <label className="block">
        テンプレート本文 (Jinja2)
        <textarea
          ref={textareaRef}
          data-testid={`${testIdPrefix}-body`}
          rows={8}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 font-mono text-[11px]"
          value={value}
          onChange={(event) => {
            const next = event.target.value;
            onChange(next);
            refreshCompletion(next, event.target.selectionStart);
          }}
          onKeyDown={onKeyDown}
          onKeyUp={(event) => {
            if (
              !open &&
              (event.key.startsWith("Arrow") ||
                event.key === "Home" ||
                event.key === "End")
            ) {
              refreshCompletion(value, event.currentTarget.selectionStart);
            }
          }}
          onBlur={() => setOpen(false)}
        />
      </label>

      {open && candidates.length > 0 && (
        <div
          data-testid={`${testIdPrefix}-completion`}
          className="max-h-40 overflow-auto rounded border border-slate-200 bg-white"
        >
          {candidates.map((candidate, index) => (
            <button
              key={candidate.value}
              type="button"
              data-testid={`${testIdPrefix}-completion-${candidate.value}`}
              className={`flex w-full items-center justify-between gap-2 px-2 py-1 text-left font-mono text-[11px] hover:bg-slate-50 ${
                index === selected ? "bg-blue-50" : ""
              }`}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => applyCandidate(candidate)}
            >
              <span className="truncate" title={candidate.description}>
                {candidate.value}
              </span>
              {candidate.type && (
                <span className="shrink-0 rounded bg-slate-100 px-1 text-[10px] text-slate-500">
                  {candidate.type}
                </span>
              )}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] text-slate-500">変数を挿入:</span>
        {variables.length === 0 ? (
          <span className="text-[10px] text-slate-500">
            inputs を追加してください
          </span>
        ) : (
          variables.map((variable) => (
            <button
              key={variable.name}
              type="button"
              data-testid={`${testIdPrefix}-insert-${variable.name}`}
              className="cursor-pointer rounded border border-slate-200 px-1 font-mono text-[10px] text-slate-700"
              onClick={() => insertText(`{{ ${variable.name} }}`)}
            >
              {variable.name}
            </button>
          ))
        )}
      </div>

      <p className="text-[10px] leading-tight text-slate-500">
        出力は nodes.&lt;id&gt;.output.text（string）。StrictUndefined
        のため未定義変数は失敗します。
      </p>
    </div>
  );
}
