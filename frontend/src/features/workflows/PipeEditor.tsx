import { useEffect, useState } from "react";
import type { WorkflowPipeOp } from "../../api/types";
import {
  PIPE_OP_SPECS,
  defaultPipeOp,
  pipeOpSpec,
  validatePipe,
  type PipeArgSpec,
} from "./pipeModel";

export interface PipeEditorProps {
  pipe: WorkflowPipeOp[];
  onChange: (pipe: WorkflowPipeOp[]) => void;
  idPrefix: string;
}

function opOptions() {
  return PIPE_OP_SPECS.map((option) => (
    <option key={option.op} value={option.op}>
      {option.label}
    </option>
  ));
}

function ArgField({
  arg,
  value,
  onChange,
  testId,
}: {
  arg: PipeArgSpec;
  value: unknown;
  onChange: (value: unknown) => void;
  testId: string;
}) {
  if (arg.type === "int") {
    return (
      <input
        type="number"
        min={0}
        data-testid={testId}
        className="w-20 rounded border border-slate-300 px-1 py-0.5 text-[11px]"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          const parsed = Number(raw);
          onChange(
            raw === "" || !Number.isFinite(parsed) ? undefined : parsed,
          );
        }}
      />
    );
  }
  if (arg.type === "string") {
    return (
      <input
        type="text"
        data-testid={testId}
        className="w-28 rounded border border-slate-300 px-1 py-0.5 text-[11px]"
        value={typeof value === "string" ? value : ""}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return <JsonArgField value={value} onChange={onChange} testId={testId} />;
}

/** JSON argument editor that keeps a raw draft while the text is invalid. */
function JsonArgField({
  value,
  onChange,
  testId,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
  testId: string;
}) {
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value),
  );
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    const incoming = value === undefined ? "" : JSON.stringify(value);
    setText((current) => {
      try {
        if (JSON.stringify(JSON.parse(current)) === incoming) return current;
      } catch {
        // keep the invalid draft the user is typing
      }
      setInvalid(false);
      return incoming;
    });
  }, [value]);
  return (
    <>
      <input
        type="text"
        data-testid={testId}
        aria-invalid={invalid}
        placeholder="JSON"
        className={`w-28 rounded border px-1 py-0.5 font-mono text-[11px] ${
          invalid ? "border-rose-500" : "border-slate-300"
        }`}
        value={text}
        onChange={(event) => {
          const raw = event.target.value;
          setText(raw);
          if (raw === "") {
            setInvalid(false);
            onChange(undefined);
            return;
          }
          try {
            onChange(JSON.parse(raw));
            setInvalid(false);
          } catch {
            // keep the invalid draft; do not commit a partial value
            setInvalid(true);
          }
        }}
      />
      {invalid && (
        <span className="text-[10px] text-rose-700">JSON が不正です</span>
      )}
    </>
  );
}

export default function PipeEditor({ pipe, onChange, idPrefix }: PipeEditorProps) {
  const issues = pipe.length ? validatePipe(pipe, `${idPrefix}.pipe`) : [];

  const updateOp = (index: number, op: string) => {
    const next = [...pipe];
    next[index] = defaultPipeOp(op);
    onChange(next);
  };

  const updateArg = (index: number, key: string, value: unknown) => {
    const next = [...pipe];
    const args = { ...(next[index].args ?? {}) };
    if (value === undefined) delete args[key];
    else args[key] = value;
    next[index] = { ...next[index], args };
    onChange(next);
  };

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= pipe.length) return;
    const next = [...pipe];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <div className="mt-1 space-y-1 rounded border border-sky-200 bg-sky-50/40 p-2 text-[11px]">
      {pipe.length === 0 && (
        <p className="text-[10px] text-slate-500">パイプなし</p>
      )}
      <ul className="space-y-1">
        {pipe.map((step, index) => {
          const spec = pipeOpSpec(step.op);
          return (
            <li
              key={`${idPrefix}-pipe-${index}`}
              className="flex flex-wrap items-center gap-1"
            >
              <select
                data-testid={`${idPrefix}-pipe-${index}-op`}
                className="rounded border border-slate-300 px-1 py-0.5"
                value={step.op}
                onChange={(event) => updateOp(index, event.target.value)}
              >
                {opOptions()}
              </select>
              {(spec?.args ?? []).map((arg) => (
                <label key={arg.key} className="flex items-center gap-1">
                  <span className="text-slate-500">{arg.label}</span>
                  <ArgField
                    arg={arg}
                    value={step.args?.[arg.key]}
                    onChange={(value) => updateArg(index, arg.key, value)}
                    testId={`${idPrefix}-pipe-${index}-${arg.key}`}
                  />
                </label>
              ))}
              <button
                type="button"
                className="cursor-pointer rounded border border-slate-300 px-1"
                onClick={() => move(index, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                className="cursor-pointer rounded border border-slate-300 px-1"
                onClick={() => move(index, 1)}
              >
                ↓
              </button>
              <button
                type="button"
                className="cursor-pointer text-rose-700"
                onClick={() => onChange(pipe.filter((_, i) => i !== index))}
              >
                削除
              </button>
            </li>
          );
        })}
      </ul>
      <select
        data-testid={`${idPrefix}-pipe-add`}
        className="cursor-pointer rounded border border-slate-300 px-1 py-0.5"
        value=""
        onChange={(event) => {
          if (!event.target.value) return;
          onChange([...pipe, defaultPipeOp(event.target.value)]);
        }}
      >
        <option value="">＋ 演算子を追加</option>
        {opOptions()}
      </select>
      {issues.length > 0 && (
        <ul
          data-testid={`${idPrefix}-pipe-issues`}
          className="text-[10px] text-rose-700"
        >
          {issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`}>{issue.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
