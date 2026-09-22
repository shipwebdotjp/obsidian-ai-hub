import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import StructuredValueEditor from "./StructuredValueEditor";

const groups = [
  {
    label: "実行入力",
    fields: [{ path: "run.inputs.task", type: "string" }],
  },
];

describe("StructuredValueEditor", () => {
  it("adds a new key with an empty string value", async () => {
    const onChange = vi.fn();
    render(
      <StructuredValueEditor
        testIdPrefix="sv"
        value={{}}
        onChange={onChange}
        referenceGroups={groups}
      />,
    );
    await userEvent.type(screen.getByTestId("sv-new-key"), "task");
    await userEvent.click(screen.getByTestId("sv-add-key"));
    expect(onChange).toHaveBeenCalledWith({ task: "" });
  });

  it("toggles a value to a typed reference", async () => {
    const onChange = vi.fn();
    render(
      <StructuredValueEditor
        testIdPrefix="sv2"
        value={{ task: "hello" }}
        onChange={onChange}
        referenceGroups={groups}
      />,
    );
    await userEvent.click(screen.getByText("参照"));
    expect(onChange).toHaveBeenCalledWith({ task: { $ref: "" } });
  });

  it("removes a key", async () => {
    const onChange = vi.fn();
    render(
      <StructuredValueEditor
        testIdPrefix="sv3"
        value={{ a: "1", b: "2" }}
        onChange={onChange}
        referenceGroups={groups}
      />,
    );
    await userEvent.click(screen.getAllByText("削除")[0]);
    expect(onChange).toHaveBeenCalledWith({ b: "2" });
  });
});
