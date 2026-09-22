import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import SchemaAuthoringForm from "./SchemaAuthoringForm";

const schema = {
  type: "object",
  properties: {
    topic: { type: "string", description: "調査テーマ" },
    tags: { type: "array", items: { type: "string" } },
  },
  required: ["topic"],
  additionalProperties: false,
};

describe("SchemaAuthoringForm", () => {
  it("renders a row per property", () => {
    render(
      <SchemaAuthoringForm
        testIdPrefix="s"
        schema={schema}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("s-topic-name")).toHaveValue("topic");
    expect(screen.getByTestId("s-tags-type")).toHaveValue("array");
    expect(screen.getByTestId("s-topic-required")).toBeChecked();
  });

  it("adds a new property", async () => {
    const onChange = vi.fn();
    render(
      <SchemaAuthoringForm
        testIdPrefix="s2"
        schema={schema}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByTestId("s2-new-name"), "extra");
    await userEvent.click(screen.getByTestId("s2-add"));
    const next = onChange.mock.calls[0][0];
    expect(Object.keys(next.properties)).toContain("extra");
  });

  it("toggles required and removes a property", async () => {
    const onChange = vi.fn();
    render(
      <SchemaAuthoringForm
        testIdPrefix="s3"
        schema={schema}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByTestId("s3-tags-required"));
    expect(onChange.mock.calls[0][0].required).toEqual(["topic", "tags"]);

    onChange.mockClear();
    await userEvent.click(screen.getAllByText("削除")[0]);
    expect(Object.keys(onChange.mock.calls[0][0].properties)).not.toContain(
      "topic",
    );
  });

  it("switches to raw JSON editing", async () => {
    render(
      <SchemaAuthoringForm
        testIdPrefix="s4"
        schema={schema}
        onChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByTestId("s4-toggle-json"));
    expect(screen.getByTestId("s4-json")).toBeInTheDocument();
  });

  it("rejects a duplicate rename and reverts the draft", async () => {
    const onChange = vi.fn();
    render(
      <SchemaAuthoringForm
        testIdPrefix="d"
        schema={schema}
        onChange={onChange}
      />,
    );
    const input = screen.getByTestId("d-topic-name");
    await userEvent.clear(input);
    await userEvent.type(input, "tags");
    await userEvent.tab();
    expect(onChange).not.toHaveBeenCalled();
    expect(input).toHaveValue("topic");
    expect(
      screen.getByText("同名のプロパティが既にあります"),
    ).toBeInTheDocument();
  });

  it("edits array-of-object item schemas", () => {
    render(
      <SchemaAuthoringForm
        testIdPrefix="o"
        schema={{
          type: "object",
          properties: {
            rows: {
              type: "array",
              items: { type: "object", properties: {}, additionalProperties: false },
            },
          },
        }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("o-rows-items-new-name")).toBeInTheDocument();
  });

  it("rejects a non-object root in raw JSON mode", async () => {
    render(
      <SchemaAuthoringForm
        testIdPrefix="r"
        schema={schema}
        onChange={vi.fn()}
      />,
    );
    await userEvent.click(screen.getByTestId("r-toggle-json"));
    const textarea = screen.getByTestId("r-json");
    await userEvent.clear(textarea);
    await userEvent.paste("[]");
    expect(screen.getByText("object が必要です")).toBeInTheDocument();
  });
});
