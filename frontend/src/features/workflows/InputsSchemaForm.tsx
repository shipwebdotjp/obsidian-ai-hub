import { useState, type ChangeEvent } from "react";

export interface InputsSchemaFormProps {
  schema: Record<string, unknown>;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  errors?: string[];
}

interface FieldSpec {
  name: string;
  type: string;
  enumValues?: unknown[];
  required: boolean;
}

export function fieldsFromSchema(
  schema: Record<string, unknown> | undefined,
): FieldSpec[] {
  const properties = (schema?.properties ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const required = new Set(
    Array.isArray(schema?.required) ? (schema?.required as string[]) : [],
  );
  return Object.entries(properties).map(([name, spec]) => ({
    name,
    type: String(spec?.type ?? "string"),
    enumValues: Array.isArray(spec?.enum) ? (spec.enum as unknown[]) : undefined,
    required: required.has(name),
  }));
}

function coerce(type: string, raw: string): unknown {
  if (type === "integer") {
    const parsed = Number.parseInt(raw, 10);
    return Number.isNaN(parsed) ? raw : parsed;
  }
  if (type === "number") {
    const parsed = Number.parseFloat(raw);
    return Number.isNaN(parsed) ? raw : parsed;
  }
  return raw;
}

/** JSON textarea that keeps raw text locally and only commits valid JSON. */
function JsonField({
  testId,
  value,
  onCommit,
}: {
  testId: string;
  value: unknown;
  onCommit: (value: unknown) => void;
}) {
  const [text, setText] = useState(() =>
    value === undefined ? "" : JSON.stringify(value),
  );
  const [invalid, setInvalid] = useState(false);
  return (
    <>
      <textarea
        data-testid={testId}
        rows={3}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
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

export default function InputsSchemaForm({
  schema,
  values,
  onChange,
  errors = [],
}: InputsSchemaFormProps) {
  const fields = fieldsFromSchema(schema);
  const update = (name: string, value: unknown) =>
    onChange({ ...values, [name]: value });
  const errorList =
    errors.length > 0 ? (
      <ul data-testid="workflow-input-errors" className="text-xs text-rose-700">
        {errors.map((error) => (
          <li key={error}>{error}</li>
        ))}
      </ul>
    ) : null;

  if (fields.length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-500">入力項目はありません。</p>
        {errorList}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {fields.map((field) => {
        const value = values[field.name];
        const testId = `workflow-input-${field.name}`;
        if (field.type === "boolean") {
          return (
            <label
              key={field.name}
              className="flex cursor-pointer items-center gap-2 text-sm"
            >
              <input
                type="checkbox"
                data-testid={testId}
                checked={value === true}
                onChange={(event: ChangeEvent<HTMLInputElement>) =>
                  update(field.name, event.target.checked)
                }
              />
              {field.name}
              {field.required && <span className="text-rose-600">*</span>}
            </label>
          );
        }
        if (field.enumValues) {
          return (
            <label key={field.name} className="block text-sm">
              <span className="mb-1 block text-slate-700">
                {field.name}
                {field.required && <span className="text-rose-600">*</span>}
              </span>
              <select
                data-testid={testId}
                className="w-full rounded border border-slate-300 px-2 py-1"
                value={value === undefined || value === null ? "" : String(value)}
                onChange={(event) => update(field.name, event.target.value)}
              >
                <option value="">(未選択)</option>
                {field.enumValues.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
            </label>
          );
        }
        if (field.type === "array" || field.type === "object") {
          return (
            <label key={field.name} className="block text-sm">
              <span className="mb-1 block text-slate-700">
                {field.name}
                {field.required && <span className="text-rose-600">*</span>}
              </span>
              <JsonField
                testId={testId}
                value={value}
                onCommit={(next) => update(field.name, next)}
              />
            </label>
          );
        }
        return (
          <label key={field.name} className="block text-sm">
            <span className="mb-1 block text-slate-700">
              {field.name}
              {field.required && <span className="text-rose-600">*</span>}
            </span>
            <input
              type={field.type === "integer" || field.type === "number" ? "number" : "text"}
              data-testid={testId}
              className="w-full rounded border border-slate-300 px-2 py-1"
              value={value === undefined || value === null ? "" : String(value)}
              onChange={(event) =>
                update(field.name, coerce(field.type, event.target.value))
              }
            />
          </label>
        );
      })}
      {errorList}
    </div>
  );
}
