import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InputsSchemaForm from "./InputsSchemaForm";

describe("InputsSchemaForm", () => {
  it("renders every declared field", () => {
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: { topic: { type: "string" }, count: { type: "integer" } },
          required: ["topic"],
        }}
        values={{}}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("workflow-input-topic")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-input-count")).toBeInTheDocument();
  });

  it("emits typed values on change", async () => {
    const onChange = vi.fn();
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: { count: { type: "integer" } },
        }}
        values={{}}
        onChange={onChange}
      />,
    );
    await userEvent.type(screen.getByTestId("workflow-input-count"), "3");
    expect(onChange).toHaveBeenLastCalledWith({ count: 3 });
  });

  it("renders nested object fields and emits the nested value", async () => {
    const onChange = vi.fn();
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: {
            options: {
              type: "object",
              properties: { label: { type: "string" } },
            },
          },
        }}
        values={{}}
        onChange={onChange}
      />,
    );
    await userEvent.type(
      screen.getByTestId("workflow-input-options.label"),
      "x",
    );
    expect(onChange).toHaveBeenLastCalledWith({ options: { label: "x" } });
  });

  it("toggles a leaf to a typed reference", async () => {
    const onChange = vi.fn();
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: { topic: { type: "string" } },
        }}
        values={{}}
        onChange={onChange}
        allowReferences
        referenceGroups={[
          {
            label: "実行入力",
            fields: [{ path: "run.inputs.topic", type: "string" }],
          },
        ]}
      />,
    );
    await userEvent.click(screen.getByText("参照"));
    expect(onChange).toHaveBeenLastCalledWith({ topic: { $ref: "" } });
  });

  it("renders a backend x-ui widget hint instead of a text input", () => {
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: { start_date: { type: "string", "x-ui": "date" } },
        }}
        values={{}}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("workflow-input-start_date")).toHaveAttribute(
      "type",
      "date",
    );
  });

  it("offers the reference toggle for boolean fields too", async () => {
    const onChange = vi.fn();
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: { done: { type: "boolean" } },
        }}
        values={{}}
        onChange={onChange}
        allowReferences
        referenceGroups={[]}
      />,
    );
    await userEvent.click(screen.getByText("参照"));
    expect(onChange).toHaveBeenLastCalledWith({ done: { $ref: "" } });
  });
});

  it("offers expression mode for date fields and emits $expr", async () => {
    const onChange = vi.fn();
    render(
      <InputsSchemaForm
        schema={{
          type: "object",
          properties: {
            day: { type: "string", format: "date" },
          },
        }}
        values={{}}
        onChange={onChange}
        allowExpressions
        expressionReferenceGroups={[
          {
            label: "実行コンテキスト (run.context)",
            fields: [{ path: "run.context.reference_time", type: "string" }],
          },
        ]}
      />,
    );
    await userEvent.click(screen.getByText("式"));
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as {
      day: { $expr: { result: string; anchor: unknown } };
    };
    expect(next.day.$expr.result).toBe("date");
    expect(next.day.$expr.anchor).toBe("now");
    expect(screen.queryByTestId("workflow-input-day-math")).not.toBeInTheDocument();
  });
