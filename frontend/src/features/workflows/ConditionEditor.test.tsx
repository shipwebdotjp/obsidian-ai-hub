import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConditionEditor from "./ConditionEditor";

describe("ConditionEditor", () => {
  it("emits a default condition when enabled and null when disabled", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <ConditionEditor
        idPrefix="c1"
        condition={null}
        candidates={["run.inputs.flag"]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByTestId("c1-enable"));
    expect(onChange).toHaveBeenCalledWith({
      from_path: "run.inputs.flag",
      operator: "equals",
      value: "",
    });

    onChange.mockClear();
    rerender(
      <ConditionEditor
        idPrefix="c1"
        condition={{ from_path: "run.inputs.flag", operator: "equals", value: true }}
        candidates={["run.inputs.flag"]}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByTestId("c1-enable"));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("drops the value when switching to exists", async () => {
    const onChange = vi.fn();
    render(
      <ConditionEditor
        idPrefix="c2"
        condition={{ from_path: "run.inputs.flag", operator: "equals", value: 1 }}
        candidates={["run.inputs.flag"]}
        onChange={onChange}
      />,
    );
    await userEvent.selectOptions(screen.getByTestId("c2-operator"), "exists");
    expect(onChange).toHaveBeenCalledWith({
      from_path: "run.inputs.flag",
      operator: "exists",
    });
  });

  it("commits a JSON array for the in operator", async () => {
    const onChange = vi.fn();
    render(
      <ConditionEditor
        idPrefix="c3"
        condition={{ from_path: "run.inputs.flag", operator: "in", value: [] }}
        candidates={["run.inputs.flag"]}
        onChange={onChange}
      />,
    );
    const textarea = screen.getByTestId("c3-value-json");
    await userEvent.clear(textarea);
    await userEvent.click(textarea);
    await userEvent.paste("[1,2]");
    expect(onChange).toHaveBeenLastCalledWith({
      from_path: "run.inputs.flag",
      operator: "in",
      value: [1, 2],
    });
  });
});
