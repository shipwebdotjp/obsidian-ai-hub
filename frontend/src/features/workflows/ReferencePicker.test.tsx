import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReferencePicker from "./ReferencePicker";
import type { ReferenceGroup } from "./graphModel";

const groups: ReferenceGroup[] = [
  {
    label: "実行入力 (run.inputs)",
    fields: [{ path: "run.inputs.topic", type: "string" }],
  },
  {
    label: "計画 (abc123)",
    fields: [
      { path: "nodes.abc123.output.plan", type: "string" },
      { path: "nodes.abc123.output.risks", type: "array" },
    ],
  },
];

describe("ReferencePicker", () => {
  it("keeps the candidate list collapsed until opened", () => {
    render(
      <ReferencePicker idPrefix="rp0" groups={groups} value="" onChange={vi.fn()} />,
    );
    expect(screen.queryByTestId("rp0-ref-list")).not.toBeInTheDocument();
  });

  it("selects a candidate path on click", async () => {
    const onChange = vi.fn();
    render(
      <ReferencePicker
        idPrefix="rp"
        groups={groups}
        value=""
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByTestId("rp-ref-toggle"));
    await userEvent.click(screen.getByText("nodes.abc123.output.plan"));
    expect(onChange).toHaveBeenCalledWith("nodes.abc123.output.plan");
  });

  it("filters candidates by the search text", async () => {
    render(
      <ReferencePicker
        idPrefix="rp2"
        groups={groups}
        value=""
        onChange={vi.fn()}
        defaultOpen
      />,
    );
    await userEvent.type(screen.getByTestId("rp2-ref-filter"), "risks");
    expect(screen.queryByText("run.inputs.topic")).not.toBeInTheDocument();
    expect(screen.getByText("nodes.abc123.output.risks")).toBeInTheDocument();
  });

  it("warns when the free-text value is not a reference shape", () => {
    render(
      <ReferencePicker
        idPrefix="rp4"
        groups={groups}
        value="not-a-ref"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("rp4-ref-warning")).toBeInTheDocument();
  });

  it("edits the raw path and clears it", async () => {
    const onChange = vi.fn();
    render(
      <ReferencePicker
        idPrefix="rp3"
        groups={groups}
        value="run.inputs.topic"
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByText("クリア"));
    expect(onChange).toHaveBeenCalledWith("");
  });
});
