import { describe, expect, it } from "vitest";
import {
  defaultPipeOp,
  pipeOpSpec,
  validatePipe,
} from "./pipeModel";

describe("pipeModel", () => {
  it("validates accepted ops and rejects bad args", () => {
    expect(validatePipe([{ op: "upper" }])).toEqual([]);
    expect(
      validatePipe([{ op: "slice", args: { limit: 3, offset: 1 } }]),
    ).toEqual([]);
    expect(validatePipe([{ op: "bogus" }]).length).toBeGreaterThan(0);
    expect(validatePipe([{ op: "truncate" }]).length).toBeGreaterThan(0);
    expect(
      validatePipe([{ op: "truncate", args: { max_len: -1 } }]).length,
    ).toBeGreaterThan(0);
    expect(validatePipe([{ op: "replace", args: { frm: "" } }]).length).toBeGreaterThan(0);
    expect(
      validatePipe([{ op: "upper", args: { x: 1 } }]).length,
    ).toBeGreaterThan(0);
  });

  it("rejects nested references in args", () => {
    expect(
      validatePipe([
        { op: "default", args: { value: { $ref: "run.inputs.x" } } },
      ]).length,
    ).toBeGreaterThan(0);
  });

  it("treats a null default value as provided and mirrors exact shapes", () => {
    expect(validatePipe([{ op: "default", args: { value: null } }])).toEqual([]);
    // Exact-shape parity with the backend: malformed / empty refs are literals.
    expect(
      validatePipe([{ op: "default", args: { value: { $ref: "" } } }]),
    ).toEqual([]);
    expect(
      validatePipe([
        { op: "default", args: { value: { $ref: "x", extra: 1 } } },
      ]),
    ).toEqual([]);
  });

  it("mirrors step-shape checks", () => {
    expect(validatePipe([{ op: "upper", args: [] }]).length).toBeGreaterThan(0);
    expect(
      validatePipe([{ op: "upper", extra: 1 } as never]).length,
    ).toBeGreaterThan(0);
  });

  it("builds default args for required fields", () => {
    const slice = defaultPipeOp("slice");
    expect(slice.op).toBe("slice");
    expect(slice.args).toEqual({ limit: 0 });
    expect(pipeOpSpec("default")?.args[0].required).toBe(true);
  });

  it("caps the number of ops", () => {
    expect(validatePipe(Array.from({ length: 21 }, () => ({ op: "upper" }))).length).toBeGreaterThan(0);
  });
});

describe("pipeModel filter/sort/unique", () => {
  it("accepts valid filter/sort/unique args", () => {
    expect(
      validatePipe([
        { op: "filter", args: { key: "start", op: "gt", value: "x" } },
      ]),
    ).toEqual([]);
    expect(
      validatePipe([
        { op: "filter", args: { key: "start", op: "exists" } },
      ]),
    ).toEqual([]);
    expect(
      validatePipe([
        { op: "filter", args: { key: "s", op: "gte", value: "d", as: "date" } },
      ]),
    ).toEqual([]);
    expect(validatePipe([{ op: "sort", args: { order: "desc" } }])).toEqual([]);
    expect(validatePipe([{ op: "unique", args: { key: "title" } }])).toEqual([]);
  });

  it("treats filter op as optional with an eq default", () => {
    expect(
      validatePipe([{ op: "filter", args: { key: "k", value: 1 } }]),
    ).toEqual([]);
    expect(
      validatePipe([{ op: "filter", args: { key: "k", op: "in", value: [1] } }]),
    ).toEqual([]);
  });

  it("rejects invalid filter/sort/unique args", () => {
    expect(
      validatePipe([{ op: "filter", args: { op: "eq", value: 1 } }]).length,
    ).toBeGreaterThan(0);
    expect(
      validatePipe([
        { op: "filter", args: { key: "k", op: "exists", value: 1 } },
      ]).length,
    ).toBeGreaterThan(0);
    expect(
      validatePipe([{ op: "filter", args: { key: "k", op: "eq" } }]).length,
    ).toBeGreaterThan(0);
    expect(
      validatePipe([
        { op: "filter", args: { key: "k", op: "in", value: "x" } },
      ]).length,
    ).toBeGreaterThan(0);
    expect(
      validatePipe([
        { op: "filter", args: { key: "k", op: "contains", value: 1 } },
      ]).length,
    ).toBeGreaterThan(0);
    expect(
      validatePipe([
        { op: "filter", args: { key: "k", op: "exists", as: "date" } },
      ]).length,
    ).toBeGreaterThan(0);
    expect(validatePipe([{ op: "sort", args: { order: "up" } }]).length).toBeGreaterThan(0);
    expect(validatePipe([{ op: "unique", args: { key: "" } }]).length).toBeGreaterThan(0);
  });

  it("reports a single issue for a missing or invalid filter arg", () => {
    const missing = validatePipe([
      { op: "filter", args: { key: "k", op: "in" } },
    ]);
    expect(missing.filter((issue) => issue.message.includes("args.value"))).toHaveLength(1);
    const badAs = validatePipe([
      { op: "filter", args: { key: "k", op: "exists", as: "bogus" } },
    ]);
    expect(badAs.filter((issue) => issue.message.includes("args.as"))).toHaveLength(1);
  });

  it("defaults enum args and exposes options", () => {
    expect(defaultPipeOp("filter").args).toMatchObject({ key: "", op: "eq" });
    expect(defaultPipeOp("sort").args).toEqual({ order: "asc" });
    expect(pipeOpSpec("filter")?.args.find((a) => a.key === "as")?.options?.length).toBe(2);
    expect(pipeOpSpec("sort")?.args.find((a) => a.key === "order")?.defaultValue).toBe("asc");
  });
});
