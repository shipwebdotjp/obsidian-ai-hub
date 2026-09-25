import { describe, expect, it } from "vitest";
import {
  parseEnumInput,
  validateSchemaSubset,
  withPropertyAdded,
  withPropertyRemoved,
  withPropertyRenamed,
  withRequiredToggled,
} from "./schemaModel";

describe("schemaModel", () => {
  it("flags v1 subset violations", () => {
    const codes = validateSchemaSubset({
      type: "object",
      properties: {
        a: { $ref: "#/x" },
        b: { type: "array" },
        c: { type: "bogus" },
      },
      required: ["missing"],
    }).map((issue) => `${issue.path}:${issue.message}`);

    expect(codes.some((entry) => entry.includes("$ref"))).toBe(true);
    expect(codes.some((entry) => entry.includes("items"))).toBe(true);
    expect(codes.some((entry) => entry.includes("bogus"))).toBe(true);
    expect(codes.some((entry) => entry.includes("missing"))).toBe(true);
  });

  it("accepts a valid subset schema", () => {
    expect(
      validateSchemaSubset({
        type: "object",
        properties: {
          topic: { type: "string" },
          tags: { type: "array", items: { type: "string" } },
          mode: { type: "string", enum: ["a", "b"] },
        },
        required: ["topic"],
        additionalProperties: false,
      }),
    ).toEqual([]);
  });

  it("adds, renames, removes properties and toggles required", () => {
    let schema = withPropertyAdded({ type: "object", properties: {} }, "a", {
      type: "string",
    });
    schema = withPropertyAdded(schema, "b", { type: "integer" });
    schema = withRequiredToggled(schema, "a", true);
    expect(Object.keys(schema.properties ?? {})).toEqual(["a", "b"]);
    expect(schema.required).toEqual(["a"]);

    schema = withPropertyRenamed(schema, "a", "topic");
    expect(Object.keys(schema.properties ?? {})).toEqual(["topic", "b"]);
    expect(schema.required).toEqual(["topic"]);

    schema = withPropertyRemoved(schema, "topic");
    expect(Object.keys(schema.properties ?? {})).toEqual(["b"]);
    expect(schema.required).toEqual([]);
  });

  it("flags required even without a properties object (backend parity)", () => {
    const issues = validateSchemaSubset({ type: "object", required: "x" });
    expect(issues.some((issue) => issue.path.endsWith(".required"))).toBe(true);
  });

  it("allows renaming to a prototype-named key", () => {
    const schema = withPropertyRenamed(
      { type: "object", properties: { a: { type: "string" } } },
      "a",
      "toString",
    );
    expect(Object.keys(schema.properties ?? {})).toEqual(["toString"]);
  });

  it("accepts item count limits on arrays", () => {
    expect(
      validateSchemaSubset({
        type: "array",
        items: { type: "string" },
        minItems: 1,
        maxItems: 5,
      }),
    ).toEqual([]);
  });

  it("rejects invalid item count limits", () => {
    const negative = validateSchemaSubset({
      type: "array",
      items: { type: "string" },
      minItems: -1,
    });
    expect(negative.some((issue) => issue.path.endsWith(".minItems"))).toBe(true);

    const inverted = validateSchemaSubset({
      type: "array",
      items: { type: "string" },
      minItems: 3,
      maxItems: 1,
    });
    expect(inverted.some((issue) => issue.message.includes("maxItems"))).toBe(
      true,
    );
  });

  it("parses enum text with numeric coercion", () => {
    expect(parseEnumInput("a, b ,,c", "string")).toEqual(["a", "b", "c"]);
    expect(parseEnumInput("1, 2, x", "integer")).toEqual([1, 2, "x"]);
  });
});
