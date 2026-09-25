import { useState, type ChangeEvent, type ReactNode } from "react";
import type { WorkflowSchemaField } from "../../api/types";
import { isReferenceValue, type ReferenceGroup } from "./graphModel";
import ReferenceValueEditor from "./ReferenceValueEditor";
import ExpressionEditor from "./ExpressionEditor";
import {
  defaultExpression,
  isExpressionValue,
} from "./expressionModel";
import { renderFieldWidget } from "./SchemaFieldWidget";

export interface InputsSchemaFormProps {
  schema: WorkflowSchemaField | Record<string, unknown>;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  errors?: string[];
  /** When set, each leaf may hold a typed ``{"$ref": ...}`` instead of a literal. */
  allowReferences?: boolean;
  referenceGroups?: ReferenceGroup[];
  /** When set, string leaves may hold a ``{"$expr": ...}`` date expression. */
  allowExpressions?: boolean;
  /** Anchor references for expressions; limit to context in the Run form. */
  expressionReferenceGroups?: ReferenceGroup[];
  /** Whether expression anchors may reference Node/Loop outputs. */
  allowNodeAnchors?: boolean;
  /** Test id prefix; nested fields append their path. */
  testIdPrefix?: string;
}

function asField(schema: unknown): WorkflowSchemaField {
  return (
    schema && typeof schema === "object" ? schema : {}
  ) as WorkflowSchemaField;
}

function coerce(type: string | undefined, raw: string): unknown {
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

function FieldHeader({
  label,
  required,
  description,
  actions,
}: {
  label: string;
  required: boolean;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-1 flex items-start justify-between gap-2">
      <div>
        <span className="text-slate-700">
          {label}
          {required && <span className="text-rose-600">*</span>}
        </span>
        {description && (
          <p className="text-[10px] leading-tight text-slate-500">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 gap-1">{actions}</div>
      )}
    </div>
  );
}

function ModeButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      className="cursor-pointer rounded border border-slate-300 px-1 text-[10px] text-slate-600"
      onClick={onClick}
    >
      {label}
    </button>
  );
}

interface SchemaValueFieldProps {
  label: string;
  field: WorkflowSchemaField;
  value: unknown;
  required: boolean;
  onChange: (value: unknown) => void;
  idPath: string;
  testIdPrefix: string;
  allowReferences: boolean;
  referenceGroups: ReferenceGroup[];
  allowExpressions: boolean;
  expressionReferenceGroups: ReferenceGroup[];
  allowNodeAnchors: boolean;
}

function SchemaValueField({
  label,
  field,
  value,
  required,
  onChange,
  idPath,
  testIdPrefix,
  allowReferences,
  referenceGroups,
  allowExpressions,
  expressionReferenceGroups,
  allowNodeAnchors,
}: SchemaValueFieldProps) {
  const testId = `${testIdPrefix}-${idPath}`;
  const unsupported = field["x-unsupported"] === true;
  const expressionCapable =
    allowExpressions && (field.type === "string" || field.type === undefined);

  // Render an existing expression independently of the toggle so a stored
  // value is never coerced to ``[object Object]`` by the literal widgets.
  if (isExpressionValue(value)) {
    return (
      <div className="block text-sm">
        <FieldHeader
          label={label}
          required={required}
          description={field.description}
          actions={
            <>
              <ModeButton label="値を入力" onClick={() => onChange("")} />
              {allowReferences && (
                <ModeButton
                  label="参照"
                  onClick={() => onChange({ $ref: "" })}
                />
              )}
            </>
          }
        />
        <ExpressionEditor
          idPrefix={testId}
          value={value}
          onChange={onChange}
          referenceGroups={expressionReferenceGroups}
          allowNodeAnchors={allowNodeAnchors}
          expectedFormat={field.format}
        />
      </div>
    );
  }

  if (allowReferences && isReferenceValue(value)) {
    return (
      <div className="block text-sm">
        <FieldHeader
          label={label}
          required={required}
          description={field.description}
          actions={
            <>
              <ModeButton label="値を入力" onClick={() => onChange("")} />
              {expressionCapable && (
                <ModeButton
                  label="式"
                  onClick={() => onChange(defaultExpression(field.format))}
                />
              )}
            </>
          }
        />
        <ReferenceValueEditor
          idPrefix={testId}
          groups={referenceGroups}
          value={value}
          onChange={onChange}
        />
      </div>
    );
  }

  const literalActions =
    allowReferences || expressionCapable ? (
      <>
        {allowReferences && (
          <ModeButton label="参照" onClick={() => onChange({ $ref: "" })} />
        )}
        {expressionCapable && (
          <ModeButton
            label="式"
            onClick={() => onChange(defaultExpression(field.format))}
          />
        )}
      </>
    ) : undefined;
  const header = (
    <FieldHeader
      label={label}
      required={required}
      description={field.description}
      actions={literalActions}
    />
  );

  if (unsupported) {
    return (
      <div className="block text-sm">
        {header}
        <JsonField testId={testId} value={value} onCommit={onChange} />
      </div>
    );
  }

  if (field["x-ui"]) {
    const widget = renderFieldWidget(field["x-ui"], value, onChange, testId);
    if (widget) {
      return (
        <div className="block text-sm">
          {header}
          {widget}
        </div>
      );
    }
  }

  if (field.type === "boolean") {
    return (
      <div className="block text-sm">
        {header}
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            data-testid={testId}
            checked={value === true}
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              onChange(event.target.checked)
            }
          />
          <span className="text-slate-500">true / false</span>
        </label>
      </div>
    );
  }

  if (Array.isArray(field.enum) && field.enum.length > 0) {
    return (
      <div className="block text-sm">
        {header}
        <select
          data-testid={testId}
          className="w-full rounded border border-slate-300 px-2 py-1"
          value={value === undefined || value === null ? "" : String(value)}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") {
              onChange(undefined);
              return;
            }
            const match = field.enum?.find((option) => String(option) === raw);
            onChange(match !== undefined ? match : raw);
          }}
        >
          <option value="">(未選択)</option>
          {field.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      </div>
    );
  }

  if (field.type === "object") {
    const properties = field.properties;
    if (!properties || Object.keys(properties).length === 0) {
      return (
        <div className="block text-sm">
          {header}
          <JsonField testId={testId} value={value} onCommit={onChange} />
        </div>
      );
    }
    const objectValue =
      value && typeof value === "object" && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {};
    const childRequired = new Set(field.required ?? []);
    return (
      <div className="space-y-2 rounded border border-slate-200 p-2">
        {header}
        {Object.entries(properties).map(([childName, childField]) => (
          <SchemaValueField
            key={childName}
            label={childName}
            field={childField}
            value={objectValue[childName]}
            required={childRequired.has(childName)}
            onChange={(next) => onChange({ ...objectValue, [childName]: next })}
            idPath={`${idPath}.${childName}`}
            testIdPrefix={testIdPrefix}
            allowReferences={allowReferences}
            referenceGroups={referenceGroups}
            allowExpressions={allowExpressions}
            expressionReferenceGroups={expressionReferenceGroups}
            allowNodeAnchors={allowNodeAnchors}
          />
        ))}
      </div>
    );
  }

  if (field.type === "array") {
    const items = field.items;
    const itemIsScalar =
      items &&
      items["x-unsupported"] !== true &&
      items.type !== "object" &&
      items.type !== "array" &&
      !items.properties;
    if (!itemIsScalar) {
      return (
        <div className="block text-sm">
          {header}
          <JsonField testId={testId} value={value} onCommit={onChange} />
        </div>
      );
    }
    const list = Array.isArray(value) ? value : [];
    const minItems =
      typeof field.minItems === "number" ? field.minItems : undefined;
    const maxItems =
      typeof field.maxItems === "number" ? field.maxItems : undefined;
    const canRemove = minItems === undefined || list.length > minItems;
    const canAdd = maxItems === undefined || list.length < maxItems;
    return (
      <div className="block text-sm">
        {header}
        <div className="space-y-1">
          {list.map((item, index) => (
            <div key={index} className="flex items-center gap-1">
              <SchemaValueField
                label={`${index}`}
                field={items}
                value={item}
                required={false}
                onChange={(next) => {
                  const copy = [...list];
                  copy[index] = next;
                  onChange(copy);
                }}
                idPath={`${idPath}.${index}`}
                testIdPrefix={testIdPrefix}
                allowReferences={allowReferences}
                referenceGroups={referenceGroups}
                allowExpressions={allowExpressions}
                expressionReferenceGroups={expressionReferenceGroups}
                allowNodeAnchors={allowNodeAnchors}
              />
              <button
                type="button"
                className="cursor-pointer text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!canRemove}
                onClick={() => onChange(list.filter((_, i) => i !== index))}
              >
                削除
              </button>
            </div>
          ))}
          <button
            type="button"
            className="cursor-pointer rounded border border-slate-300 px-2 py-0.5 text-[11px] disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!canAdd}
            onClick={() => onChange([...list, ""])}
          >
            追加
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="block text-sm">
      {header}
      <input
        type={
          field.type === "integer" || field.type === "number"
            ? "number"
            : "text"
        }
        data-testid={testId}
        className="w-full rounded border border-slate-300 px-2 py-1"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(event) => {
          const raw = event.target.value;
          if (raw === "") {
            onChange(field.type === "string" ? "" : undefined);
            return;
          }
          onChange(coerce(field.type, raw));
        }}
      />
    </div>
  );
}

export default function InputsSchemaForm({
  schema,
  values,
  onChange,
  errors = [],
  allowReferences = false,
  referenceGroups = [],
  allowExpressions = false,
  expressionReferenceGroups,
  allowNodeAnchors = true,
  testIdPrefix = "workflow-input",
}: InputsSchemaFormProps) {
  const anchorGroups = expressionReferenceGroups ?? referenceGroups;
  const root = asField(schema);
  const properties = root.properties ?? {};
  const required = new Set(root.required ?? []);
  const update = (name: string, value: unknown) =>
    onChange({ ...values, [name]: value });

  const errorList =
    errors.length > 0 ? (
      <ul
        data-testid="workflow-input-errors"
        className="text-xs text-rose-700"
      >
        {errors.map((error) => (
          <li key={error}>{error}</li>
        ))}
      </ul>
    ) : null;

  if (Object.keys(properties).length === 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-slate-500">入力項目はありません。</p>
        {errorList}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {Object.entries(properties).map(([name, field]) => (
        <SchemaValueField
          key={name}
          label={name}
          field={field}
          value={values[name]}
          required={required.has(name)}
          onChange={(value) => update(name, value)}
          idPath={name}
          testIdPrefix={testIdPrefix}
          allowReferences={allowReferences}
          referenceGroups={referenceGroups}
          allowExpressions={allowExpressions}
          expressionReferenceGroups={anchorGroups}
          allowNodeAnchors={allowNodeAnchors}
        />
      ))}
      {errorList}
    </div>
  );
}
