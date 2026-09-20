import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import InputsSchemaForm, { fieldsFromSchema } from "./InputsSchemaForm";

describe("InputsSchemaForm", () => {
  it("derives fields and required flags from the schema subset", () => {
    const fields = fieldsFromSchema({
      type: "object",
      properties: { topic: { type: "string" }, count: { type: "integer" } },
      required: ["topic"],
    });
    expect(fields.map((f) => f.name)).toEqual(["topic", "count"]);
    expect(fields[0].required).toBe(true);
    expect(fields[1].required).toBe(false);
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
});
