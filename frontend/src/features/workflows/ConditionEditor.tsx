import { useEffect, useState } from "react";
import {
  CONDITION_OPERATORS,
  parseConditionValue,
  type ConditionOperator,
} from "./graphModel";

export interface ConditionEditorProps {
  condition: Record<string, unknown> | null;
  candidates: string[];
  onChange: (condition: Record<string, unknown> | null) => void;
  /** Test id / datalist prefix; must be unique per editor instance. */
  idPrefix: string;
}

function conditionValueText(value: unknown): string {
  if (value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

export default function ConditionEditor({
  condition,
  candidates,
  onChange,
  idPrefix,
}: ConditionEditorProps) {
  const operator = (condition?.operator as ConditionOperator) ?? "equals";
  const [jsonText, setJsonText] = useState(() =>
    operator === "in" ? JSON.stringify(condition?.value ?? []) : "",
  );
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    if (operator === "in") {
      setJsonText(JSON.stringify(condition?.value ?? []));
      setJsonError(null);
    }
    // Re-seed only when the operator switches to `in`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operator]);

  const listId = `${idPrefix}-candidates`;

  const setOperator = (next: ConditionOperator) => {
    if (!condition) return;
    if (next === "exists") {
      const { value: _value, ...rest } = condition;
      onChange({ ...rest, operator: next });
      return;
    }
    const value =
      next === "in"
        ? Array.isArray(condition.value)
          ? condition.value
          : []
        : (condition.value ?? "");
    onChange({ ...condition, operator: next, value });
  };

  let valueField = null;
  if (condition && operator === "exists") {
    valueField = (
      <p className="text-[11px] text-slate-500">
        from_path の値が存在すれば真。
      </p>
    );
  } else if (condition && operator === "in") {
    const errorId = `${idPrefix}-value-json-error`;
    valueField = (
      <label className="block">
        value (JSON 配列)
        <textarea
          data-testid={`${idPrefix}-value-json`}
          aria-invalid={jsonError !== null}
          aria-describedby={jsonError ? errorId : undefined}
          rows={2}
          className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
          value={jsonText}
          onChange={(event) => {
            const text = event.target.value;
            setJsonText(text);
            const parsed = parseConditionValue(text, "in");
            if (parsed.ok) {
              setJsonError(null);
              onChange({ ...condition, value: parsed.value });
            } else {
              setJsonError(parsed.error);
            }
          }}
        />
        {jsonError && (
          <span id={errorId} className="text-rose-700">
            {jsonError}
          </span>
        )}
      </label>
    );
  } else if (condition) {
    valueField = (
      <label className="block">
        value
        <input
          data-testid={`${idPrefix}-value`}
          className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
          value={conditionValueText(condition.value)}
          onChange={(event) => {
            const parsed = parseConditionValue(event.target.value, "equals");
            if (parsed.ok) {
              onChange({ ...condition, value: parsed.value });
            }
          }}
        />
      </label>
    );
  }

  return (
    <div className="space-y-1 rounded border border-slate-200 p-2">
      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          data-testid={`${idPrefix}-enable`}
          checked={condition !== null}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? {
                    from_path: candidates[0] ?? "",
                    operator: "equals",
                    value: "",
                  }
                : null,
            )
          }
        />
        条件付き分岐
      </label>

      {condition && (
        <>
          <label className="block">
            from_path
            <input
              list={listId}
              data-testid={`${idPrefix}-from-path`}
              className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
              value={String(condition.from_path ?? "")}
              onChange={(event) =>
                onChange({ ...condition, from_path: event.target.value })
              }
            />
            <datalist id={listId}>
              {candidates.map((candidate) => (
                <option key={candidate} value={candidate} />
              ))}
            </datalist>
          </label>

          <label className="block">
            operator
            <select
              data-testid={`${idPrefix}-operator`}
              className="ml-1 rounded border border-slate-300 px-1 py-0.5"
              value={operator}
              onChange={(event) =>
                setOperator(event.target.value as ConditionOperator)
              }
            >
              {CONDITION_OPERATORS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>

          {valueField}
        </>
      )}
    </div>
  );
}
