import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PipeEditor from "./PipeEditor";

describe("PipeEditor", () => {
  it("adds an operator and emits the new pipe", async () => {
    const onChange = vi.fn();
    render(<PipeEditor idPrefix="p" pipe={[]} onChange={onChange} />);
    await userEvent.selectOptions(
      screen.getByTestId("p-pipe-add"),
      "slice",
    );
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as { op: string; args: unknown }[];
    expect(next[0].op).toBe("slice");
    expect(next[0].args).toEqual({ limit: 0 });
  });

  it("edits an argument value", async () => {
    const onChange = vi.fn();
    render(
      <PipeEditor
        idPrefix="p"
        pipe={[{ op: "truncate", args: { max_len: 5 } }]}
        onChange={onChange}
      />,
    );
    const field = screen.getByTestId("p-pipe-0-max_len");
    await userEvent.clear(field);
    await userEvent.type(field, "9");
    expect(onChange).toHaveBeenCalled();
  });

  it("shows validation errors for missing required args", () => {
    render(
      <PipeEditor
        idPrefix="p"
        pipe={[{ op: "pluck", args: {} }]}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("p-pipe-issues")).toBeInTheDocument();
  });

  it("does not flag an empty pipe (plain reference)", () => {
    render(<PipeEditor idPrefix="p" pipe={[]} onChange={vi.fn()} />);
    expect(screen.queryByTestId("p-pipe-issues")).not.toBeInTheDocument();
  });

  it("renders filter enum args as selects and emits the chosen op", async () => {
    const onChange = vi.fn();
    render(
      <PipeEditor
        idPrefix="p"
        pipe={[{ op: "filter", args: { key: "title", op: "eq", value: "x" } }]}
        onChange={onChange}
      />,
    );
    const opSelect = screen.getByTestId("p-pipe-0-op") as HTMLSelectElement;
    expect(opSelect.tagName).toBe("SELECT");
    await userEvent.selectOptions(opSelect, "contains");
    const next = onChange.mock.calls[0][0] as { args: Record<string, unknown> }[];
    expect(next[0].args.op).toBe("contains");
  });

  it("adds a sort op with no required args", async () => {
    const onChange = vi.fn();
    render(<PipeEditor idPrefix="p" pipe={[]} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByTestId("p-pipe-add"), "sort");
    const next = onChange.mock.calls[0][0] as { op: string }[];
    expect(next[0].op).toBe("sort");
  });

  it("clears an optional string arg by deleting the key", async () => {
    const onChange = vi.fn();
    render(
      <PipeEditor
        idPrefix="p"
        pipe={[{ op: "sort", args: { key: "title" } }]}
        onChange={onChange}
      />,
    );
    await userEvent.clear(screen.getByTestId("p-pipe-0-key"));
    const next = onChange.mock.calls.at(-1)?.[0] as { args: Record<string, unknown> }[];
    expect(next[0].args).not.toHaveProperty("key");
  });

  it("keeps a raw JSON draft instead of re-quoting it", async () => {
    render(
      <PipeEditor
        idPrefix="p"
        pipe={[{ op: "default", args: { value: null } }]}
        onChange={vi.fn()}
      />,
    );
    const field = screen.getByTestId("p-pipe-0-value") as HTMLInputElement;
    await userEvent.clear(field);
    await userEvent.type(field, "hello");
    expect((field as HTMLInputElement).value).toBe("hello");
  });
});
