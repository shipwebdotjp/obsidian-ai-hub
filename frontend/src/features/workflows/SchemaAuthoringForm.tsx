import { useEffect, useState } from "react";
import type { WorkflowSchemaField } from "../../api/types";
import {
  SCHEMA_FIELD_TYPES,
  defaultFieldForType,
  emptyObjectSchema,
  enumInputText,
  parseEnumInput,
  schemaProperties,
  schemaRequired,
  validateSchemaSubset,
  withPropertyAdded,
  withPropertyRemoved,
  withPropertyRenamed,
  withPropertyUpdated,
  withRequiredToggled,
  type SchemaFieldType,
} from "./schemaModel";

export interface SchemaAuthoringFormProps {
  schema: WorkflowSchemaField;
  onChange: (schema: WorkflowSchemaField) => void;
  testIdPrefix: string;
  /** Nested forms leave validation to the root to avoid duplicate lists. */
  showIssues?: boolean;
}

const SCALAR_ENUM_TYPES = new Set(["string", "integer", "number"]);

interface PropertyEditorProps {
  name: string;
  field: WorkflowSchemaField;
  required: boolean;
  testIdPrefix: string;
  isNameTaken: (candidate: string) => boolean;
  onRename: (next: string) => void;
  onUpdate: (field: WorkflowSchemaField) => void;
  onToggleRequired: (required: boolean) => void;
  onRemove: () => void;
}

function PropertyEditor({
  name,
  field,
  required,
  testIdPrefix,
  isNameTaken,
  onRename,
  onUpdate,
  onToggleRequired,
  onRemove,
}: PropertyEditorProps) {
  const [nameDraft, setNameDraft] = useState(name);
  const [nameError, setNameError] = useState(false);
  const [enumDraft, setEnumDraft] = useState(() => enumInputText(field));

  useEffect(() => {
    setEnumDraft(enumInputText(field));
  }, [field.type, field.enum]);

  const type = (field.type ?? "string") as SchemaFieldType;
  const commitName = () => {
    const trimmed = nameDraft.trim();
    if (!trimmed || trimmed === name) {
      setNameDraft(name);
      return;
    }
    if (isNameTaken(trimmed)) {
      setNameDraft(name);
      setNameError(true);
      return;
    }
    setNameError(false);
    onRename(trimmed);
  };
  const commitEnum = () => {
    const values = parseEnumInput(enumDraft, field.type);
    const next = { ...field };
    if (values.length > 0) next.enum = values;
    else delete next.enum;
    onUpdate(next);
  };

  return (
    <div className="space-y-1 rounded border border-slate-200 p-2">
      <div className="flex items-center gap-1">
        <input
          data-testid={`${testIdPrefix}-name`}
          className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
          value={nameDraft}
          onChange={(event) => {
            setNameDraft(event.target.value);
            setNameError(false);
          }}
          onBlur={commitName}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitName();
            }
          }}
        />
        <label className="flex shrink-0 cursor-pointer items-center gap-1 text-[11px]">
          <input
            type="checkbox"
            data-testid={`${testIdPrefix}-required`}
            checked={required}
            onChange={(event) => onToggleRequired(event.target.checked)}
          />
          必須
        </label>
        <button
          type="button"
          className="shrink-0 cursor-pointer text-[11px] text-rose-700"
          onClick={onRemove}
        >
          削除
        </button>
      </div>
      {nameError && (
        <p className="text-[10px] text-rose-700">
          同名のプロパティが既にあります
        </p>
      )}

      <div className="flex items-center gap-1">
        <select
          data-testid={`${testIdPrefix}-type`}
          className="rounded border border-slate-300 px-1 py-0.5 text-[11px]"
          value={type}
          onChange={(event) => {
            const nextType = event.target.value as SchemaFieldType;
            const next = defaultFieldForType(nextType);
            if (field.description) next.description = field.description;
            if (SCALAR_ENUM_TYPES.has(nextType) && Array.isArray(field.enum)) {
              next.enum = field.enum;
            }
            if (nextType === "array" && field.items) next.items = field.items;
            onUpdate(next);
          }}
        >
          {SCHEMA_FIELD_TYPES.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        <input
          data-testid={`${testIdPrefix}-description`}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-[11px]"
          placeholder="説明"
          value={typeof field.description === "string" ? field.description : ""}
          onChange={(event) =>
            onUpdate({ ...field, description: event.target.value })
          }
        />
      </div>

      {SCALAR_ENUM_TYPES.has(type) && (
        <input
          data-testid={`${testIdPrefix}-enum`}
          className="w-full rounded border border-slate-300 px-1 py-0.5 text-[11px]"
          placeholder="enum（カンマ区切り、省略可）"
          value={enumDraft}
          onChange={(event) => setEnumDraft(event.target.value)}
          onBlur={commitEnum}
        />
      )}

      {type === "array" && (
        <div className="space-y-1">
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-slate-500">items</span>
            <select
              data-testid={`${testIdPrefix}-items-type`}
              className="rounded border border-slate-300 px-1 py-0.5 text-[11px]"
              value={field.items?.type ?? "string"}
              onChange={(event) => {
                const itemType = event.target.value as SchemaFieldType;
                onUpdate({
                  ...field,
                  type: "array",
                  items: defaultFieldForType(itemType),
                });
              }}
            >
              {SCHEMA_FIELD_TYPES.filter((value) => value !== "array").map(
                (value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ),
              )}
            </select>
          </div>
          {field.items?.type === "object" && (
            <SchemaAuthoringForm
              schema={field.items}
              onChange={(sub) => onUpdate({ ...field, type: "array", items: sub })}
              testIdPrefix={`${testIdPrefix}-items`}
              showIssues={false}
            />
          )}
        </div>
      )}

      {type === "object" && (
        <SchemaAuthoringForm
          schema={field}
          onChange={onUpdate}
          testIdPrefix={`${testIdPrefix}-child`}
          showIssues={false}
        />
      )}
    </div>
  );
}

/**
 * Guided editor for the v1 JSON Schema subset used by ``inputs_schema`` /
 * ``output_schema`` / ``state_schema``.
 *
 * A raw JSON toggle stays available for advanced cases; both paths share the
 * same backend-mirroring subset validation.
 */
export default function SchemaAuthoringForm({
  schema,
  onChange,
  testIdPrefix,
  showIssues = true,
}: SchemaAuthoringFormProps) {
  const [rawMode, setRawMode] = useState(false);
  const [rawText, setRawText] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const root: WorkflowSchemaField =
    schema && schema.type === "object" ? schema : emptyObjectSchema();
  const properties = schemaProperties(root);
  const required = new Set(schemaRequired(root));
  const issues = showIssues ? validateSchemaSubset(root) : [];

  const toggleRaw = () => {
    if (!rawMode) {
      setRawText(JSON.stringify(root, null, 2));
      setRawError(null);
    }
    setRawMode((value) => !value);
  };

  const addProperty = () => {
    const name = newName.trim();
    if (!name || Object.prototype.hasOwnProperty.call(properties, name)) return;
    onChange(
      withPropertyAdded(root, name, { type: "string", description: "" }),
    );
    setNewName("");
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-slate-500">
          {Object.keys(properties).length} プロパティ
        </span>
        <button
          type="button"
          data-testid={`${testIdPrefix}-toggle-json`}
          className="cursor-pointer rounded border border-slate-300 px-1 text-[10px] text-slate-600"
          onClick={toggleRaw}
        >
          {rawMode ? "フォームで編集" : "JSONで編集"}
        </button>
      </div>

      {rawMode ? (
        <div className="space-y-1">
          <textarea
            data-testid={`${testIdPrefix}-json`}
            rows={10}
            className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono text-[11px]"
            value={rawText}
            onChange={(event) => {
              const text = event.target.value;
              setRawText(text);
              try {
                const parsed = JSON.parse(text);
                if (
                  !parsed ||
                  typeof parsed !== "object" ||
                  Array.isArray(parsed)
                ) {
                  setRawError("object が必要です");
                  return;
                }
                if (parsed.type !== "object") {
                  setRawError('root は type: "object" が必要です');
                  return;
                }
                setRawError(null);
                onChange(parsed as WorkflowSchemaField);
              } catch {
                setRawError("JSON が不正です");
              }
            }}
          />
          {rawError && <span className="text-rose-700">{rawError}</span>}
        </div>
      ) : (
        <>
          <label className="flex cursor-pointer items-center gap-1 text-[11px]">
            <input
              type="checkbox"
              data-testid={`${testIdPrefix}-additional`}
              checked={root.additionalProperties === true}
              onChange={(event) =>
                onChange({
                  ...root,
                  type: "object",
                  additionalProperties: event.target.checked,
                })
              }
            />
            未定義のプロパティを許可する
          </label>

          {Object.entries(properties).map(([name, field]) => (
            <PropertyEditor
              key={name}
              name={name}
              field={field}
              required={required.has(name)}
              testIdPrefix={`${testIdPrefix}-${name}`}
              isNameTaken={(candidate) =>
                candidate !== name &&
                Object.prototype.hasOwnProperty.call(properties, candidate)
              }
              onRename={(next) => onChange(withPropertyRenamed(root, name, next))}
              onUpdate={(next) => onChange(withPropertyUpdated(root, name, next))}
              onToggleRequired={(value) =>
                onChange(withRequiredToggled(root, name, value))
              }
              onRemove={() => onChange(withPropertyRemoved(root, name))}
            />
          ))}

          <div className="flex items-center gap-1">
            <input
              data-testid={`${testIdPrefix}-new-name`}
              className="w-full rounded border border-slate-300 px-1 py-0.5 text-[11px]"
              placeholder="プロパティ名を追加"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addProperty();
                }
              }}
            />
            <button
              type="button"
              data-testid={`${testIdPrefix}-add`}
              className="cursor-pointer whitespace-nowrap rounded border border-slate-300 px-2 py-0.5 text-[11px]"
              onClick={addProperty}
            >
              追加
            </button>
          </div>
        </>
      )}

      {issues.length > 0 && (
        <ul
          data-testid={`${testIdPrefix}-issues`}
          className="text-[11px] text-amber-700"
        >
          {issues.map((issue, index) => (
            <li key={`${issue.path}-${index}`}>
              {issue.path}: {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
