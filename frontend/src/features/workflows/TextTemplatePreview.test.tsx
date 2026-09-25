import { useState } from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TextTemplatePreview from "./TextTemplatePreview";
import { useTextTemplatePreview } from "./useTextTemplatePreview";
import { previewTextTemplate } from "../../api/client";

vi.mock("../../api/client", () => ({
  previewTextTemplate: vi.fn(),
}));

const mockedPreview = vi.mocked(previewTextTemplate);

describe("TextTemplatePreview", () => {
  it("shows the rendered output", () => {
    render(
      <TextTemplatePreview
        preview={{ rendered: "予定: A", errors: [], pending: false }}
        sampleValues={{ events: [] }}
        onChangeSampleValues={vi.fn()}
        onGenerateScaffold={vi.fn()}
      />,
    );
    expect(screen.getByTestId("text-template-preview-output")).toHaveTextContent(
      "予定: A",
    );
  });

  it("shows render errors instead of output", () => {
    render(
      <TextTemplatePreview
        preview={{ rendered: null, errors: ["bad"], pending: false }}
        sampleValues={{}}
        onChangeSampleValues={vi.fn()}
        onGenerateScaffold={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("text-template-preview-errors"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("text-template-preview-output"),
    ).not.toBeInTheDocument();
  });

  it("invokes the scaffold and sample-change callbacks", async () => {
    const onGenerateScaffold = vi.fn();
    const onChangeSampleValues = vi.fn();
    render(
      <TextTemplatePreview
        preview={{ rendered: "", errors: [], pending: false }}
        sampleValues={{ events: [] }}
        onChangeSampleValues={onChangeSampleValues}
        onGenerateScaffold={onGenerateScaffold}
      />,
    );
    await userEvent.click(screen.getByTestId("text-template-sample-scaffold"));
    expect(onGenerateScaffold).toHaveBeenCalled();

    const textarea = screen.getByTestId("text-template-sample-values");
    fireEvent.change(textarea, { target: { value: '{"events":[1]}' } });
    expect(onChangeSampleValues).toHaveBeenLastCalledWith({ events: [1] });
  });

  it("keeps the raw JSON while typing instead of reformatting", () => {
    function SampleHarness() {
      const [values, setValues] = useState<Record<string, unknown>>({
        events: [],
      });
      return (
        <TextTemplatePreview
          preview={{ rendered: "", errors: [], pending: false }}
          sampleValues={values}
          onChangeSampleValues={setValues}
          onGenerateScaffold={vi.fn()}
        />
      );
    }
    render(<SampleHarness />);
    const textarea = screen.getByTestId("text-template-sample-values");
    fireEvent.change(textarea, { target: { value: '{"events":[1]}' } });
    expect(textarea).toHaveValue('{"events":[1]}');
  });
});

function HookHarness() {
  const state = useTextTemplatePreview("{{ events }}", { events: [] }, {
    debounceMs: 0,
  });
  return <pre data-testid="hook-output">{state.rendered ?? ""}</pre>;
}

describe("useTextTemplatePreview", () => {
  beforeEach(() => {
    mockedPreview.mockReset();
  });

  it("renders via the backend preview endpoint", async () => {
    mockedPreview.mockResolvedValue({
      ok: true,
      rendered: "予定: A",
      errors: [],
    });
    render(<HookHarness />);
    await waitFor(() =>
      expect(screen.getByTestId("hook-output")).toHaveTextContent("予定: A"),
    );
    expect(mockedPreview).toHaveBeenCalledWith({
      template: "{{ events }}",
      values: { events: [] },
    });
  });
});
