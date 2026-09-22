import { useState } from "react";
import { isReferenceValue, type ReferenceGroup } from "./graphModel";
import ReferencePicker from "./ReferencePicker";

export interface StructuredValueEditorProps {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  referenceGroups: ReferenceGroup[];
  testIdPrefix: string;
  /** Key-name suggestions (e.g. ``task`` / ``context``). */
  suggestions?: string[];
}

function kindOf(value: unknown): string {
  if (isReferenceValue(value)) return "参照";
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

interface ValueEditorProps {
  value: unknown;
  onChange: (value: unknown) => void;
  referenceGroups: ReferenceGroup[];
  idPath: string;
  testIdPrefix: string;
}

function ValueEditor({
  value,
  onChange,
  referenceGroups,
  idPath,
  testIdPrefix,
}: ValueEditorProps) {
  const testId = `${testIdPrefix}-${idPath}`;

  if (isReferenceValue(value)) {
    return (
      <ReferencePicker
        idPrefix={testId}
        groups={referenceGroups}
        value={value.$ref}
        onChange={(path) => onChange({ $ref: path })}
      />
    );
  }

  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return (
      <StructuredValueEditor
        value={value as Record<string, unknown>}
        onChange={onChange}
        referenceGroups={referenceGroups}
        testIdPrefix={`${testIdPrefix}-${idPath}`}
      />
    );
  }

  if (Array.isArray(value)) {
    return (
      <JsonField
        testId={testId}
        value={value}
        onCommit={(next) => onChange(next)}
      />
    );
  }

  if (typeof value === "boolean") {
    return (
      <input
        type="checkbox"
        data-testid={testId}
        checked={value}
        onChange={(event) => onChange(event.target.checked)}
      />
    );
  }

  if (typeof value === "number") {
    return (
      <input
        type="number"
        data-testid={testId}
        className="w-full rounded border border-slate-300 px-1 py-0.5"
        value={value}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") {
            onChange(undefined);
            return;
          }
          const parsed = Number(raw);
          onChange(Number.isNaN(parsed) ? raw : parsed);
        }}
      />
    );
  }

  return (
    <input
      type="text"
      data-testid={testId}
      className="w-full rounded border border-slate-300 px-1 py-0.5"
      value={value === null || value === undefined ? "" : String(value)}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function JsonField({
  testId,
  value,
  onCommit,
}: {
  testId: string;
  value: unknown;
  onCommit: (value: unknown) => void;
}) {
  const [text, setText] = useState(() => JSON.stringify(value));
  const [invalid, setInvalid] = useState(false);
  return (
    <>
      <textarea
        data-testid={testId}
        rows={2}
        className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
        value={text}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            onCommit(JSON.parse(next));
            setInvalid(false);
          } catch {
            setInvalid(true);
          }
        }}
      />
      {invalid && <span className="text-rose-700">JSON が不正です</span>}
    </>
  );
}

/**
 * Free-form JSON object editor with per-value literal/reference toggle.
 *
 * Agent Node ``inputs`` have no schema by contract, so this guides the common
 * shape (key/value rows, nesting, typed references) without inventing one.
 */
export default function StructuredValueEditor({
  value,
  onChange,
  referenceGroups,
  testIdPrefix,
  suggestions = [],
}: StructuredValueEditorProps) {
  const [keyDraft, setKeyDraft] = useState("");
  const entries = Object.entries(value);

  const addKey = () => {
    const name = keyDraft.trim();
    if (!name || Object.prototype.hasOwnProperty.call(value, name)) return;
    onChange({ ...value, [name]: "" });
    setKeyDraft("");
  };

  return (
    <div className="space-y-2">
      {entries.length === 0 && (
        <p className="text-[11px] text-slate-500">キーがありません。</p>
      )}
      {entries.map(([key, child]) => (
        <div
          key={key}
          className="space-y-1 rounded border border-slate-200 p-2"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="truncate font-mono text-[11px] text-slate-700">
              {key}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              <span className="rounded bg-slate-100 px-1 text-[10px] text-slate-500">
                {kindOf(child)}
              </span>
              <button
                type="button"
                className="cursor-pointer rounded border border-slate-300 px-1 text-[10px] text-slate-600"
                onClick={() =>
                  onChange({
                    ...value,
                    [key]: isReferenceValue(child) ? "" : { $ref: "" },
                  })
                }
              >
                {isReferenceValue(child) ? "値を入力" : "参照"}
              </button>
              <button
                type="button"
                className="cursor-pointer text-[11px] text-rose-700"
                onClick={() => {
                  const copy = { ...value };
                  delete copy[key];
                  onChange(copy);
                }}
              >
                削除
              </button>
            </span>
          </div>
          <ValueEditor
            value={child}
            onChange={(next) => onChange({ ...value, [key]: next })}
            referenceGroups={referenceGroups}
            idPath={key}
            testIdPrefix={testIdPrefix}
          />
        </div>
      ))}

      <div className="flex items-center gap-1">
        <input
          list={`${testIdPrefix}-key-suggestions`}
          data-testid={`${testIdPrefix}-new-key`}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-[11px]"
          placeholder="キーを追加 (例: task)"
          value={keyDraft}
          onChange={(event) => setKeyDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addKey();
            }
          }}
        />
        <datalist id={`${testIdPrefix}-key-suggestions`}>
          {suggestions.map((suggestion) => (
            <option key={suggestion} value={suggestion} />
          ))}
        </datalist>
        <button
          type="button"
          data-testid={`${testIdPrefix}-add-key`}
          className="cursor-pointer whitespace-nowrap rounded border border-slate-300 px-2 py-0.5 text-[11px]"
          onClick={addKey}
        >
          追加
        </button>
      </div>
    </div>
  );
}
