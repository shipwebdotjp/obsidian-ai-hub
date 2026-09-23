import { describe, expect, it } from "vitest";
import {
  defaultExpression,
  isExpressionValue,
  validateDateMath,
  validateExpressionValue,
} from "./expressionModel";
import {
  buildReferenceGroups,
  validateReference,
  type ReferenceScope,
} from "./graphModel";
import type { WorkflowNode } from "../../api/types";

describe("expressionModel", () => {
  it("parses compact date math", () => {
    expect(validateDateMath("/w+6d")).toEqual([]);
    expect(validateDateMath("-1M")).toEqual([]);
    expect(validateDateMath("")).toEqual([]);
    expect(validateDateMath("+d").length).toBeGreaterThan(0);
    expect(validateDateMath("2d").length).toBeGreaterThan(0);
    expect(validateDateMath("/w6").length).toBeGreaterThan(0);
  });

  it("builds a default expression matching the field format", () => {
    expect(defaultExpression("date-time").$expr.result).toBe("datetime");
    expect(defaultExpression("date").$expr.result).toBe("date");
    expect(isExpressionValue(defaultExpression())).toBe(true);
    expect(isExpressionValue({ $ref: "run.inputs.x" })).toBe(false);
  });

  it("validates an expression value", () => {
    expect(validateExpressionValue(defaultExpression("date"))).toEqual([]);
    const bad = defaultExpression();
    bad.$expr.math = "+d";
    expect(validateExpressionValue(bad).length).toBeGreaterThan(0);
  });

  it("checks result against the expected format", () => {
    const value = defaultExpression("date");
    expect(
      validateExpressionValue(value, { expectedFormat: "date" }),
    ).toEqual([]);
    expect(
      validateExpressionValue(value, { expectedFormat: "date-time" }).length,
    ).toBeGreaterThan(0);
  });

  it("treats timezone and week start as optional", () => {
    const value = defaultExpression();
    delete (value.$expr as { timezone?: string }).timezone;
    delete (value.$expr as { week_starts_on?: string }).week_starts_on;
    expect(validateExpressionValue(value)).toEqual([]);
  });

  it("limits anchors to context when node anchors are disallowed", () => {
    const value = defaultExpression();
    value.$expr.anchor = { $ref: "nodes.n1.output.day" };
    expect(validateExpressionValue(value, { allowNodeAnchors: true })).toEqual([]);
    expect(
      validateExpressionValue(value, { allowNodeAnchors: false }).length,
    ).toBeGreaterThan(0);
    value.$expr.anchor = { $ref: "run.context.reference_time" };
    expect(
      validateExpressionValue(value, { allowNodeAnchors: false }),
    ).toEqual([]);
  });
});

describe("graphModel run.context", () => {
  it("accepts run.context.reference_time", () => {
    const scope: ReferenceScope = { inputsKeys: [], nodeIds: [] };
    expect(validateReference("run.context.reference_time", scope)).toBeNull();
    expect(validateReference("run.context.other", scope)).not.toBeNull();
  });

  it("offers the context reference group", () => {
    const nodes: WorkflowNode[] = [];
    const groups = buildReferenceGroups(nodes, null, {
      type: "object",
      properties: {},
    });
    const paths = groups.flatMap((group) => group.fields.map((f) => f.path));
    expect(paths).toContain("run.context.reference_time");
  });
});
