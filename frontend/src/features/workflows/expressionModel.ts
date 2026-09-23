import { REFERENCE_TIME_REF, type GraphIssue } from "./graphModel";

/** Compact date-math expression mirrored from the backend `$expr` contract. */
export type ExpressionResult = "date" | "datetime";
export type Weekday =
  | "monday"
  | "tuesday"
  | "wednesday"
  | "thursday"
  | "friday"
  | "saturday"
  | "sunday";

export interface WorkflowExpression {
  kind: "date_math";
  version: 1;
  anchor: "now" | { $ref: string };
  math: string;
  timezone: string;
  week_starts_on: Weekday;
  result: ExpressionResult;
}

export interface ExpressionValue {
  $expr: WorkflowExpression;
}

export const WEEKDAYS: Weekday[] = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
];
export const DEFAULT_TIMEZONE = "Asia/Tokyo";

/** True when ``value`` is exactly ``{"$expr": {...}}``. */
export function isExpressionValue(value: unknown): value is ExpressionValue {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Object.keys(record).length === 1 &&
    !!record.$expr &&
    typeof record.$expr === "object" &&
    !Array.isArray(record.$expr)
  );
}

export function defaultExpression(
  format?: string,
  anchor: WorkflowExpression["anchor"] = "now",
): ExpressionValue {
  return {
    $expr: {
      kind: "date_math",
      version: 1,
      anchor,
      math: "",
      timezone: DEFAULT_TIMEZONE,
      week_starts_on: "monday",
      result: format === "date-time" ? "datetime" : "date",
    },
  };
}

const DATE_MATH_TOKEN_RE = /(?<op>[/+\-])(?<amount>\d*)(?<unit>[yMwdhms])/g;

/** Return human-readable errors for a compact date-math string. */
export function validateDateMath(math: string): string[] {
  const errors: string[] = [];
  let position = 0;
  const tokens = [...math.matchAll(DATE_MATH_TOKEN_RE)];
  for (const match of tokens) {
    const start = match.index ?? 0;
    if (start !== position) {
      errors.push(`構文が不正です: '${math.slice(position, start)}'`);
      return errors;
    }
    position = start + match[0].length;
  }
  if (position !== math.length) {
    errors.push(`構文が不正です: '${math.slice(position)}'`);
    return errors;
  }
  // A token without an amount is only valid for the floor operator.
  for (const match of tokens) {
    const [op, amount, unit] = [match[1], match[2], match[3]];
    if (op !== "/" && amount === "") {
      errors.push(`'${op}${unit}' には数値が必要です`);
    }
    if (op === "/" && amount !== "") {
      errors.push(`'/' には数値を付けられません`);
    }
  }
  return errors;
}

export interface ExpressionValidationOptions {
  /** Allow anchors that reference Node/Loop outputs (false for Run inputs). */
  allowNodeAnchors?: boolean;
  /** Target field ``format`` from the schema, for ``result`` compatibility. */
  expectedFormat?: string;
}

export function validateExpressionValue(
  value: ExpressionValue,
  options: ExpressionValidationOptions = {},
): GraphIssue[] {
  const issues: GraphIssue[] = [];
  const expr = value.$expr;
  if (expr.kind !== "date_math") {
    issues.push({ code: "expression_kind", message: "kind は date_math が必要です" });
  }
  if (expr.version !== 1) {
    issues.push({ code: "expression_version", message: "version は 1 が必要です" });
  }
  if (expr.anchor !== "now") {
    const ref = expr.anchor?.$ref;
    if (!ref) {
      issues.push({
        code: "expression_anchor",
        message: "anchor は now または型付き参照が必要です",
      });
    } else if (
      options.allowNodeAnchors === false &&
      ref !== REFERENCE_TIME_REF
    ) {
      issues.push({
        code: "expression_anchor",
        message: `Run 入力では now または ${REFERENCE_TIME_REF} のみ参照できます`,
      });
    }
  }
  for (const error of validateDateMath(expr.math ?? "")) {
    issues.push({ code: "expression_math", message: error });
  }
  // ``timezone`` / ``week_starts_on`` are optional; only reject a present but
  // invalid value so this validator mirrors the backend contract.
  if (expr.timezone != null && expr.timezone.trim() === "") {
    issues.push({ code: "expression_timezone", message: "タイムゾーンが不正です" });
  }
  if (expr.week_starts_on != null && !WEEKDAYS.includes(expr.week_starts_on)) {
    issues.push({
      code: "expression_week",
      message: "週の開始曜日が不正です",
    });
  }
  if (expr.result !== "date" && expr.result !== "datetime") {
    issues.push({
      code: "expression_result",
      message: "result は date または datetime が必要です",
    });
  } else if (
    options.expectedFormat === "date" &&
    expr.result !== "date"
  ) {
    issues.push({
      code: "expression_result",
      message: "format 'date' には result 'date' が必要です",
    });
  } else if (
    options.expectedFormat === "date-time" &&
    expr.result !== "datetime"
  ) {
    issues.push({
      code: "expression_result",
      message: "format 'date-time' には result 'datetime' が必要です",
    });
  }
  return issues;
}
