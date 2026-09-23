import type { WorkflowSchemaField } from "../../api/types";

export type SchemaFieldType =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "object"
  | "array";

export const SCHEMA_FIELD_TYPES: SchemaFieldType[] = [
  "string",
  "integer",
  "number",
  "boolean",
  "object",
  "array",
];

export interface SchemaIssue {
  path: string;
  message: string;
}

const SUPPORTED_KEYS = new Set([
  "type",
  "properties",
  "required",
  "items",
  "enum",
  "additionalProperties",
  "description",
  "title",
  "default",
  "minimum",
  "maximum",
  "minLength",
  "maxLength",
  "pattern",
  "format",
]);

const SUPPORTED_FORMATS = new Set(["date", "date-time"]);

const UNSUPPORTED_KEYS = new Set([
  "$ref",
  "oneOf",
  "anyOf",
  "allOf",
  "not",
  "const",
  "patternProperties",
  "additionalItems",
  "dependencies",
  "definitions",
  "$defs",
  "if",
  "then",
  "else",
  "propertyNames",
]);

const SUBSET_TYPES = new Set([
  "object",
  "array",
  "string",
  "integer",
  "number",
  "boolean",
]);

export const MAX_SCHEMA_DEPTH = 8;

/** Mirror of the backend v1 JSON Schema subset check (workflow/models.py). */
export function validateSchemaSubset(
  schema: unknown,
  path = "schema",
  depth = 0,
): SchemaIssue[] {
  const issues: SchemaIssue[] = [];
  if (depth > MAX_SCHEMA_DEPTH) {
    return [{ path, message: "schema のネストが深すぎます" }];
  }
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) {
    return [{ path, message: "schema は object である必要があります" }];
  }
  const node = schema as Record<string, unknown>;
  for (const key of Object.keys(node)) {
    if (UNSUPPORTED_KEYS.has(key)) {
      issues.push({ path, message: `'${key}' は v1 では未対応です` });
    } else if (!SUPPORTED_KEYS.has(key)) {
      issues.push({ path, message: `未知の schema キー '${key}'` });
    }
  }
  const type = node.type;
  if (type !== undefined && (typeof type !== "string" || !SUBSET_TYPES.has(type))) {
    issues.push({ path, message: `type '${String(type)}' は v1 では未対応です` });
  }
  if (type === undefined && !("enum" in node)) {
    issues.push({ path, message: "type または enum が必要です" });
  }
  if (node.format !== null && node.format !== undefined) {
    const format = node.format;
    if (type !== undefined && type !== "string") {
      issues.push({ path: `${path}.format`, message: "string 型にのみ指定できます" });
    } else if (typeof format !== "string" || !SUPPORTED_FORMATS.has(format)) {
      issues.push({
        path: `${path}.format`,
        message: "'date' または 'date-time' が必要です",
      });
    }
  }
  if ("enum" in node) {
    const enumValues = node.enum;
    if (!Array.isArray(enumValues) || enumValues.length === 0) {
      issues.push({ path: `${path}.enum`, message: "空でない配列が必要です" });
    }
  }
  if (type === "object") {
    const props = node.properties;
    let propsRecord: Record<string, unknown> | null = null;
    if (props !== undefined && (typeof props !== "object" || Array.isArray(props))) {
      issues.push({ path: `${path}.properties`, message: "object が必要です" });
    } else if (props && typeof props === "object") {
      propsRecord = props as Record<string, unknown>;
      for (const [name, sub] of Object.entries(propsRecord)) {
        issues.push(
          ...validateSchemaSubset(sub, `${path}.properties.${name}`, depth + 1),
        );
      }
    }
    // ``required`` is validated whenever it is present, independent of
    // ``properties`` (mirrors the backend subset check).
    const required = node.required;
    if (
      required !== undefined &&
      (!Array.isArray(required) ||
        required.some((r) => typeof r !== "string"))
    ) {
      issues.push({
        path: `${path}.required`,
        message: "文字列の配列が必要です",
      });
    } else if (Array.isArray(required) && propsRecord) {
      for (const name of required) {
        if (!Object.prototype.hasOwnProperty.call(propsRecord, name)) {
          issues.push({
            path: `${path}.required`,
            message: `未定義のプロパティ '${name}'`,
          });
        }
      }
    }
    const additional = node.additionalProperties;
    if (additional !== undefined && typeof additional !== "boolean") {
      issues.push({
        path: `${path}.additionalProperties`,
        message: "boolean のみ対応です",
      });
    }
  } else if (type === "array") {
    if (!("items" in node)) {
      issues.push({ path, message: "array には items が必要です" });
    } else {
      issues.push(
        ...validateSchemaSubset(node.items, `${path}.items`, depth + 1),
      );
    }
  }
  return issues;
}

export function emptyObjectSchema(): WorkflowSchemaField {
  return { type: "object", properties: {}, additionalProperties: false };
}

export function schemaProperties(
  schema: WorkflowSchemaField | undefined,
): Record<string, WorkflowSchemaField> {
  const props = schema?.properties;
  return props && typeof props === "object" ? props : {};
}

export function schemaRequired(schema: WorkflowSchemaField | undefined): string[] {
  return Array.isArray(schema?.required)
    ? schema?.required.filter((name) => typeof name === "string")
    : [];
}

export function defaultFieldForType(type: SchemaFieldType): WorkflowSchemaField {
  if (type === "array") {
    return { type: "array", items: { type: "string" } };
  }
  if (type === "object") {
    return { type: "object", properties: {}, additionalProperties: false };
  }
  return { type };
}

export function withPropertyAdded(
  schema: WorkflowSchemaField,
  name: string,
  field: WorkflowSchemaField,
): WorkflowSchemaField {
  return {
    ...schema,
    type: "object",
    properties: { ...schemaProperties(schema), [name]: field },
  };
}

export function withPropertyRemoved(
  schema: WorkflowSchemaField,
  name: string,
): WorkflowSchemaField {
  const properties = { ...schemaProperties(schema) };
  delete properties[name];
  return {
    ...schema,
    type: "object",
    properties,
    required: schemaRequired(schema).filter((entry) => entry !== name),
  };
}

export function withPropertyRenamed(
  schema: WorkflowSchemaField,
  from: string,
  to: string,
): WorkflowSchemaField {
  const trimmed = to.trim();
  if (!trimmed || trimmed === from) return schema;
  const properties = schemaProperties(schema);
  if (Object.prototype.hasOwnProperty.call(properties, trimmed)) return schema;
  const next: Record<string, WorkflowSchemaField> = {};
  for (const [key, value] of Object.entries(properties)) {
    next[key === from ? trimmed : key] = value;
  }
  return {
    ...schema,
    type: "object",
    properties: next,
    required: schemaRequired(schema).map((entry) =>
      entry === from ? trimmed : entry,
    ),
  };
}

export function withPropertyUpdated(
  schema: WorkflowSchemaField,
  name: string,
  field: WorkflowSchemaField,
): WorkflowSchemaField {
  return withPropertyAdded(schema, name, field);
}

export function withRequiredToggled(
  schema: WorkflowSchemaField,
  name: string,
  required: boolean,
): WorkflowSchemaField {
  const current = new Set(schemaRequired(schema));
  if (required) current.add(name);
  else current.delete(name);
  return {
    ...schema,
    type: "object",
    required: Array.from(current),
  };
}

export function parseEnumInput(raw: string, type: string | undefined): unknown[] {
  const values = raw
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
  if (type === "integer" || type === "number") {
    return values.map((entry) => {
      const parsed = Number(entry);
      return Number.isNaN(parsed) ? entry : parsed;
    });
  }
  return values;
}

export function enumInputText(field: WorkflowSchemaField): string {
  return Array.isArray(field.enum) ? field.enum.map(String).join(", ") : "";
}
