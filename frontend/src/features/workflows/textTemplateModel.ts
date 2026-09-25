import type { WorkflowSchemaField } from "../../api/types";
import { isExpressionValue } from "./expressionModel";
import {
  isReferenceValue,
  referencePath,
  type ReferenceGroup,
} from "./graphModel";

/** A ``text_template`` input variable and the declared type of its reference. */
export interface TemplateVariable {
  name: string;
  type?: string;
  /** ``$ref`` path when the input value is a typed reference. */
  refPath?: string;
}

export interface CompletionCandidate {
  /** Full replacement text for the token fragment (e.g. ``event.title``). */
  value: string;
  type?: string;
  description?: string;
}

export interface TemplateToken {
  /** Identifier fragment immediately before the caret (may be ``""``). */
  query: string;
  /** Root variable name when the fragment is a dotted field access, else ``""``. */
  root: string;
  /** Field prefix typed after the root (without the leading dot), else ``""``. */
  fieldPrefix: string;
  /** Start offset of the fragment within the template. */
  start: number;
}

function literalType(value: unknown): string | undefined {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  switch (typeof value) {
    case "string":
      return "string";
    case "number":
      return Number.isInteger(value) ? "integer" : "number";
    case "boolean":
      return "boolean";
    case "object":
      return "object";
    default:
      return undefined;
  }
}

/**
 * Project ``config.inputs`` into completion variables, borrowing the declared
 * type of each reference from the editor's reference candidates.
 */
export function templateVariables(
  inputs: Record<string, unknown>,
  referenceGroups: ReferenceGroup[],
): TemplateVariable[] {
  const fields = referenceGroups.flatMap((group) => group.fields);
  return Object.entries(inputs).map(([name, value]) => {
    const refPath = referencePath(value);
    if (refPath) {
      const field = fields.find((candidate) => candidate.path === refPath);
      return { name, type: field?.type, refPath };
    }
    return { name, type: literalType(value) };
  });
}

function sampleFromSchema(schema: WorkflowSchemaField): unknown {
  if (schema.default !== undefined) return schema.default;
  if (schema.enum && schema.enum.length > 0) return schema.enum[0];
  switch (schema.type) {
    case "object": {
      const out: Record<string, unknown> = {};
      for (const [name, sub] of Object.entries(schema.properties ?? {})) {
        out[name] = sampleFromSchema(sub);
      }
      return out;
    }
    case "array":
      return schema.items ? [sampleFromSchema(schema.items)] : [];
    case "integer":
    case "number":
      return 0;
    case "boolean":
      return false;
    case "null":
      return null;
    default:
      return "サンプル";
  }
}

/** A placeholder value for previewing, preferring the declared schema shape. */
export function sampleValueForType(
  type?: string,
  schema?: WorkflowSchemaField | null,
): unknown {
  if (schema && !schema["x-unsupported"]) return sampleFromSchema(schema);
  switch (type) {
    case "array":
      return [];
    case "object":
      return {};
    case "integer":
    case "number":
      return 0;
    case "boolean":
      return false;
    default:
      return "サンプル";
  }
}

/**
 * Seed preview sample values: literals are reused as-is, references and
 * expressions get a type/schema-derived placeholder.
 */
export function buildSampleValues(
  variables: TemplateVariable[],
  inputs: Record<string, unknown>,
  schemaFor?: (variable: TemplateVariable) => WorkflowSchemaField | null,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const variable of variables) {
    const value = inputs[variable.name];
    if (
      value !== undefined &&
      !isReferenceValue(value) &&
      !isExpressionValue(value)
    ) {
      out[variable.name] = value;
      continue;
    }
    out[variable.name] = sampleValueForType(
      variable.type,
      schemaFor?.(variable) ?? null,
    );
  }
  return out;
}

/**
 * The identifier being typed at ``caret`` when it sits inside a ``{{ ... }}``
 * expression. Returns ``null`` outside expressions or when the fragment is not
 * an identifier.
 */
export function tokenAt(template: string, caret: number): TemplateToken | null {
  const before = template.slice(0, caret);
  const open = before.lastIndexOf("{{");
  if (open === -1) return null;
  if (before.lastIndexOf("}}") > open) return null;
  const expr = before.slice(open + 2);
  if (expr.includes("{%") || expr.includes("%}")) return null;

  const match = /([A-Za-z_][A-Za-z0-9_.]*)$/.exec(expr);
  if (!match) {
    if (expr.trim() === "") {
      return { query: "", root: "", fieldPrefix: "", start: caret };
    }
    return null;
  }
  const query = match[1];
  const start = caret - query.length;
  const dot = query.indexOf(".");
  if (dot === -1) {
    return { query, root: "", fieldPrefix: "", start };
  }
  return {
    query,
    root: query.slice(0, dot),
    fieldPrefix: query.slice(dot + 1),
    start,
  };
}

/** Map ``{% for X in Y %}`` binding names to their iterable variable name.

Only simple identifier iterables are bound; a dotted iterable (``a.b``) is left
unbound so completion offers nothing rather than a wrong schema.
*/
export function forLoopBindings(template: string): Record<string, string> {
  const bindings: Record<string, string> = {};
  const re =
    /\{%\s*for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+([A-Za-z_][A-Za-z0-9_]*)(?![\w.])/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(template)) !== null) {
    bindings[match[1]] = match[2];
  }
  return bindings;
}

function fieldCandidates(
  schema: WorkflowSchemaField | null,
  prefix: string,
  unwrapArray = false,
): { name: string; type?: string; description?: string }[] {
  if (!schema) return [];
  const object =
    unwrapArray && schema.type === "array" && schema.items
      ? schema.items
      : schema;
  if (object.type !== "object" || !object.properties) return [];
  const needle = prefix.toLowerCase();
  return Object.entries(object.properties)
    .filter(([name]) => name.toLowerCase().startsWith(needle))
    .map(([name, sub]) => ({
      name,
      type: sub.type,
      description: sub.description,
    }));
}

/**
 * Completion candidates for the token at the caret.
 *
 * ``schemaFor`` resolves a variable name (or a loop iterable name) to its JSON
 * schema; loop bindings are dereferenced to their iterable first.
 */
export function completionCandidates(
  token: TemplateToken,
  variables: TemplateVariable[],
  bindings: Record<string, string>,
  schemaFor: (name: string) => WorkflowSchemaField | null,
): CompletionCandidate[] {
  if (token.root === "") {
    const needle = token.query.toLowerCase();
    return variables
      .filter((variable) => variable.name.toLowerCase().startsWith(needle))
      .map((variable) => ({ value: variable.name, type: variable.type }));
  }
  const isLoopBinding = Object.prototype.hasOwnProperty.call(
    bindings,
    token.root,
  );
  const iterable = isLoopBinding ? bindings[token.root] : token.root;
  return fieldCandidates(
    schemaFor(iterable),
    token.fieldPrefix,
    isLoopBinding,
  ).map((field) => ({
    value: `${token.root}.${field.name}`,
    type: field.type,
    description: field.description,
  }));
}
