import { describe, expect, it } from "vitest";
import {
  buildSampleValues,
  completionCandidates,
  forLoopBindings,
  sampleValueForType,
  templateVariables,
  tokenAt,
} from "./textTemplateModel";
import type { ReferenceGroup } from "./graphModel";

const groups: ReferenceGroup[] = [
  {
    label: "実行入力 (run.inputs)",
    fields: [
      { path: "run.inputs.topic", type: "string" },
      { path: "run.inputs.events", type: "array" },
    ],
  },
];

describe("templateVariables", () => {
  it("borrows types from reference candidates and literals", () => {
    const variables = templateVariables(
      {
        events: { $ref: "run.inputs.events" },
        count: 3,
        title: "x",
      },
      groups,
    );
    expect(variables).toEqual([
      { name: "events", type: "array", refPath: "run.inputs.events" },
      { name: "count", type: "integer" },
      { name: "title", type: "string" },
    ]);
  });
});

describe("tokenAt", () => {
  it("returns null outside an expression", () => {
    expect(tokenAt("hello world", 5)).toBeNull();
    expect(tokenAt("{{ events }}", 12)).toBeNull();
  });

  it("detects a bare variable fragment", () => {
    const template = "{{ ev";
    expect(tokenAt(template, template.length)).toEqual({
      query: "ev",
      root: "",
      fieldPrefix: "",
      start: 3,
    });
  });

  it("detects a dotted field fragment", () => {
    const template = "{{ event.ti";
    expect(tokenAt(template, template.length)).toEqual({
      query: "event.ti",
      root: "event",
      fieldPrefix: "ti",
      start: 3,
    });
  });

  it("offers all variables right after the opening braces", () => {
    const template = "{{ ";
    expect(tokenAt(template, template.length)).toEqual({
      query: "",
      root: "",
      fieldPrefix: "",
      start: 3,
    });
  });
});

describe("forLoopBindings", () => {
  it("maps binding names to iterables", () => {
    const template = "{% for event in events %}{{ event.title }}{% endfor %}";
    expect(forLoopBindings(template)).toEqual({ event: "events" });
  });
});

describe("sample values", () => {
  it("derives placeholders from types", () => {
    expect(sampleValueForType("string")).toBe("サンプル");
    expect(sampleValueForType("array")).toEqual([]);
    expect(sampleValueForType("integer")).toBe(0);
  });

  it("seeds array-of-object samples from a schema", () => {
    const value = sampleValueForType("array", {
      type: "array",
      items: { type: "object", properties: { title: { type: "string" } } },
    });
    expect(value).toEqual([{ title: "サンプル" }]);
  });

  it("reuses literals and scaffolds references", () => {
    const variables = templateVariables(
      { events: { $ref: "run.inputs.events" }, count: 7 },
      groups,
    );
    const samples = buildSampleValues(variables, {
      events: { $ref: "run.inputs.events" },
      count: 7,
    });
    expect(samples).toEqual({ events: [], count: 7 });
  });
});

describe("completionCandidates", () => {
  const variables = templateVariables(
    { events: { $ref: "run.inputs.events" } },
    groups,
  );
  const schemaFor = (name: string) =>
    name === "events"
      ? {
          type: "array",
          items: {
            type: "object",
            properties: { title: { type: "string" } },
          },
        }
      : null;

  it("filters variable names by the typed prefix", () => {
    const candidates = completionCandidates(
      { query: "ev", root: "", fieldPrefix: "", start: 3 },
      variables,
      {},
      schemaFor,
    );
    expect(candidates.map((candidate) => candidate.value)).toEqual(["events"]);
  });

  it("completes fields on a loop binding", () => {
    const candidates = completionCandidates(
      { query: "event.t", root: "event", fieldPrefix: "t", start: 3 },
      variables,
      { event: "events" },
      schemaFor,
    );
    expect(candidates).toEqual([
      { value: "event.title", type: "string", description: undefined },
    ]);
  });

  it("does not offer item fields on a plain array variable", () => {
    const candidates = completionCandidates(
      { query: "events.t", root: "events", fieldPrefix: "t", start: 3 },
      variables,
      {},
      schemaFor,
    );
    expect(candidates).toEqual([]);
  });
});
