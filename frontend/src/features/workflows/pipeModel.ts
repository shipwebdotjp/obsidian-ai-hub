import type { WorkflowPipeOp } from "../../api/types";
import type { GraphIssue } from "./graphModel";

export type PipeArgType = "int" | "string" | "any" | "enum";

export interface PipeArgOption {
  value: string;
  label: string;
}

export interface PipeArgSpec {
  key: string;
  label: string;
  type: PipeArgType;
  required: boolean;
  options?: PipeArgOption[];
  defaultValue?: unknown;
}

export interface PipeOpSpec {
  op: string;
  label: string;
  args: PipeArgSpec[];
}

export const MAX_PIPE_OPS = 20;

const FILTER_AS_OPTIONS: PipeArgOption[] = [
  { value: "auto", label: "auto" },
  { value: "date", label: "date" },
];

const FILTER_OP_OPTIONS: PipeArgOption[] = [
  { value: "eq", label: "eq (=)" },
  { value: "ne", label: "ne (≠)" },
  { value: "gt", label: "gt (>)" },
  { value: "gte", label: "gte (≥)" },
  { value: "lt", label: "lt (<)" },
  { value: "lte", label: "lte (≤)" },
  { value: "in", label: "in (含まれる)" },
  { value: "not_in", label: "not_in (含まれない)" },
  { value: "contains", label: "contains (部分一致)" },
  { value: "exists", label: "exists (存在)" },
];

export const PIPE_OP_SPECS: PipeOpSpec[] = [
  { op: "upper", label: "upper (大文字)", args: [] },
  { op: "lower", label: "lower (小文字)", args: [] },
  {
    op: "truncate",
    label: "truncate (切り詰め)",
    args: [{ key: "max_len", label: "max_len", type: "int", required: true }],
  },
  {
    op: "slice",
    label: "slice (部分取得)",
    args: [
      { key: "limit", label: "limit", type: "int", required: true },
      { key: "offset", label: "offset", type: "int", required: false },
    ],
  },
  {
    op: "replace",
    label: "replace (置換)",
    args: [
      { key: "frm", label: "frm", type: "string", required: true },
      { key: "to", label: "to", type: "string", required: false },
    ],
  },
  {
    op: "pluck",
    label: "pluck (キー抽出)",
    args: [{ key: "key", label: "key", type: "string", required: true }],
  },
  {
    op: "join",
    label: "join (連結)",
    args: [{ key: "sep", label: "sep", type: "string", required: false }],
  },
  {
    op: "default",
    label: "default (空なら置換)",
    args: [{ key: "value", label: "value", type: "any", required: true }],
  },
  {
    op: "filter",
    label: "filter (選別)",
    args: [
      { key: "key", label: "key", type: "string", required: true },
      {
        key: "op",
        label: "op",
        type: "enum",
        required: false,
        defaultValue: "eq",
        options: FILTER_OP_OPTIONS,
      },
      { key: "value", label: "value", type: "any", required: false },
      {
        key: "as",
        label: "as",
        type: "enum",
        required: false,
        options: FILTER_AS_OPTIONS,
      },
    ],
  },
  {
    op: "sort",
    label: "sort (並べ替え)",
    args: [
      { key: "key", label: "key", type: "string", required: false },
      {
        key: "order",
        label: "order",
        type: "enum",
        required: false,
        defaultValue: "asc",
        options: [
          { value: "asc", label: "asc" },
          { value: "desc", label: "desc" },
        ],
      },
    ],
  },
  {
    op: "unique",
    label: "unique (重複排除)",
    args: [{ key: "key", label: "key", type: "string", required: false }],
  },
];

const FILTER_OPS = new Set(FILTER_OP_OPTIONS.map((option) => option.value));
const FILTER_AS_VALUES = new Set(FILTER_AS_OPTIONS.map((option) => option.value));
const FILTER_COMPARISON_OP_VALUES = ["eq", "ne", "gt", "gte", "lt", "lte"];
const FILTER_COMPARISON_OPS = new Set(FILTER_COMPARISON_OP_VALUES);
const FILTER_COMPARISON_HINT = FILTER_COMPARISON_OP_VALUES.map(
  (value) => `'${value}'`,
).join("/");

export function pipeOpSpec(op: string): PipeOpSpec | undefined {
  return PIPE_OP_SPECS.find((spec) => spec.op === op);
}

const ARG_DEFAULTS: Record<PipeArgType, unknown> = {
  int: 0,
  string: "",
  any: null,
  enum: null,
};

export function defaultPipeOp(op: string): WorkflowPipeOp {
  const spec = pipeOpSpec(op);
  const args: Record<string, unknown> = {};
  for (const arg of spec?.args ?? []) {
    if (!arg.required && arg.defaultValue === undefined) continue;
    if (arg.type === "enum") {
      args[arg.key] = arg.defaultValue ?? arg.options?.[0]?.value ?? "";
      continue;
    }
    args[arg.key] = arg.defaultValue ?? ARG_DEFAULTS[arg.type];
  }
  return { op, args };
}

function isInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isExactReference(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record);
  return (
    keys.includes("$ref") &&
    keys.every((key) => key === "$ref" || key === "pipe") &&
    typeof record.$ref === "string" &&
    record.$ref.trim() !== "" &&
    (!("pipe" in record) || Array.isArray(record.pipe))
  );
}

function isExactExpression(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Object.keys(record).length === 1 &&
    "$expr" in record &&
    !!record.$expr &&
    typeof record.$expr === "object" &&
    !Array.isArray(record.$expr)
  );
}

/** Mirror the backend exact-shape check for nested refs/exprs in pipe args. */
function containsRefOrExpr(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(containsRefOrExpr);
  if (isExactReference(value) || isExactExpression(value)) return true;
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some(containsRefOrExpr);
  }
  return false;
}

export function validatePipe(pipe: unknown, path = "pipe"): GraphIssue[] {
  const issues: GraphIssue[] = [];
  if (!Array.isArray(pipe)) {
    return [{ code: "pipe_shape", message: `${path}: 配列が必要です` }];
  }
  if (pipe.length === 0) {
    return [{ code: "pipe_shape", message: `${path}: 1 つ以上の演算子が必要です` }];
  }
  if (pipe.length > MAX_PIPE_OPS) {
    return [
      { code: "pipe_shape", message: `${path}: 演算子は最大 ${MAX_PIPE_OPS} 個です` },
    ];
  }
  pipe.forEach((step, index) => {
    const stepPath = `${path}[${index}]`;
    if (!step || typeof step !== "object" || Array.isArray(step)) {
      issues.push({ code: "pipe_shape", message: `${stepPath}: object が必要です` });
      return;
    }
    const record = step as Record<string, unknown>;
    const unknownKeys = Object.keys(record).filter(
      (key) => key !== "op" && key !== "args",
    );
    if (unknownKeys.length > 0) {
      issues.push({
        code: "pipe_shape",
        message: `${stepPath}: 未知のキー ${unknownKeys.join(", ")}`,
      });
    }
    const spec = pipeOpSpec(String(record.op ?? ""));
    if (!spec) {
      issues.push({
        code: "pipe_op",
        message: `${stepPath}.op: 未対応の演算子です`,
      });
      return;
    }
    if (
      record.args !== undefined &&
      (record.args === null ||
        typeof record.args !== "object" ||
        Array.isArray(record.args))
    ) {
      issues.push({
        code: "pipe_args",
        message: `${stepPath}.args: object が必要です`,
      });
      return;
    }
    const args = (record.args as Record<string, unknown> | undefined) ?? {};
    if (containsRefOrExpr(args)) {
      issues.push({
        code: "pipe_args",
        message: `${stepPath}.args: 引数に $ref / $expr は使えません`,
      });
    }
    const allowed = new Set(spec.args.map((arg) => arg.key));
    for (const key of Object.keys(args)) {
      if (!allowed.has(key)) {
        issues.push({
          code: "pipe_args",
          message: `${stepPath}.args: 未知の引数 '${key}'`,
        });
      }
    }
    for (const arg of spec.args) {
      const value = args[arg.key];
      if (
        arg.required &&
        (value === undefined || (value === null && arg.type !== "any"))
      ) {
        issues.push({
          code: "pipe_args",
          message: `${stepPath}.args.${arg.key}: 必須です`,
        });
        continue;
      }
      if (value === undefined || value === null) continue;
      if (arg.type === "int" && (!isInt(value) || value < 0)) {
        issues.push({
          code: "pipe_args",
          message: `${stepPath}.args.${arg.key}: 0 以上の整数が必要です`,
        });
      }
      if (arg.type === "string" && typeof value !== "string") {
        issues.push({
          code: "pipe_args",
          message: `${stepPath}.args.${arg.key}: 文字列が必要です`,
        });
      }
      if (
        arg.type === "string" &&
        (arg.key === "frm" || arg.key === "key") &&
        value === ""
      ) {
        issues.push({
          code: "pipe_args",
          message: `${stepPath}.args.${arg.key}: 空でない文字列が必要です`,
        });
      }
      if (arg.type === "enum") {
        const options = arg.options ?? [];
        if (!options.some((option) => option.value === value)) {
          issues.push({
            code: "pipe_args",
            message: `${stepPath}.args.${arg.key}: ${options
              .map((option) => option.value)
              .join(" / ")} のいずれかが必要です`,
          });
        }
      }
    }
    if (spec.op === "filter") {
      validateFilterArgs(args, stepPath, issues);
    }
  });
  return issues;
}

function validateFilterArgs(
  args: Record<string, unknown>,
  stepPath: string,
  issues: GraphIssue[],
): void {
  const predicate = typeof args.op === "string" ? args.op : "eq";
  if (!FILTER_OPS.has(predicate)) return;
  if (predicate === "exists") {
    if ("value" in args) {
      issues.push({
        code: "pipe_args",
        message: `${stepPath}.args.value: op 'exists' では指定できません`,
      });
    }
  } else if (!("value" in args)) {
    issues.push({
      code: "pipe_args",
      message: `${stepPath}.args.value: value が必要です`,
    });
  }
  if (
    "as" in args &&
    args.as !== undefined &&
    args.as !== null &&
    FILTER_AS_VALUES.has(String(args.as)) &&
    !FILTER_COMPARISON_OPS.has(predicate)
  ) {
    issues.push({
      code: "pipe_args",
      message: `${stepPath}.args.as: op ${FILTER_COMPARISON_HINT} でのみ指定できます`,
    });
  }
  if (
    (predicate === "in" || predicate === "not_in") &&
    "value" in args &&
    !Array.isArray(args.value)
  ) {
    issues.push({
      code: "pipe_args",
      message: `${stepPath}.args.value: op '${predicate}' では配列が必要です`,
    });
  }
  if (
    predicate === "contains" &&
    "value" in args &&
    typeof args.value !== "string"
  ) {
    issues.push({
      code: "pipe_args",
      message: `${stepPath}.args.value: op 'contains' では文字列が必要です`,
    });
  }
}
