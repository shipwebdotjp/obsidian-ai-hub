import { useState } from "react";
import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TextTemplateEditor from "./TextTemplateEditor";
import type { WorkflowSchemaField } from "../../api/types";
import { templateVariables } from "./textTemplateModel";
import type { ReferenceGroup } from "./graphModel";

const groups: ReferenceGroup[] = [
  {
    label: "実行入力 (run.inputs)",
    fields: [
      { path: "run.inputs.events", type: "array" },
      { path: "run.inputs.topic", type: "string" },
    ],
  },
];

const variables = templateVariables(
  { events: { $ref: "run.inputs.events" }, topic: { $ref: "run.inputs.topic" } },
  groups,
);

const schemaFor = (name: string): WorkflowSchemaField | null =>
  name === "events"
    ? {
        type: "array",
        items: { type: "object", properties: { title: { type: "string" } } },
      }
    : null;

function Harness({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <TextTemplateEditor
      value={value}
      onChange={setValue}
      variables={variables}
      schemaFor={schemaFor}
    />
  );
}

describe("TextTemplateEditor", () => {
  it("inserts a variable from the chip list", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByTestId("text-template-insert-events"));
    expect(screen.getByTestId("text-template-body")).toHaveValue(
      "{{ events }}",
    );
  });

  it("completes a variable typed inside an expression", async () => {
    render(<Harness />);
    const textarea = screen.getByTestId(
      "text-template-body",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "{{ ev" } });
    textarea.setSelectionRange(6, 6);
    fireEvent.keyUp(textarea, { key: "v" });

    const candidate = screen.getByTestId("text-template-completion-events");
    await userEvent.click(candidate);
    expect(textarea).toHaveValue("{{ events");
  });

  it("completes nested fields on a loop binding", () => {
    render(<Harness />);
    const textarea = screen.getByTestId(
      "text-template-body",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, {
      target: { value: "{% for event in events %}{{ event.t" },
    });
    expect(
      screen.getByTestId("text-template-completion-event.title"),
    ).toBeInTheDocument();
  });
});
