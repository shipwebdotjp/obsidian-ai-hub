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
