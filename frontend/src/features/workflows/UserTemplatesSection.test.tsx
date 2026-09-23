import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteWorkflowUserTemplate,
  exportWorkflowUserTemplate,
  importWorkflowDefinition,
  instantiateWorkflowUserTemplate,
  listWorkflowUserTemplates,
} from "../../api/client";
import UserTemplatesSection from "./UserTemplatesSection";

vi.mock("../../api/client", () => ({
  deleteWorkflowUserTemplate: vi.fn(),
  exportWorkflowUserTemplate: vi.fn(),
  importWorkflowDefinition: vi.fn(),
  instantiateWorkflowUserTemplate: vi.fn(),
  listWorkflowUserTemplates: vi.fn(),
  updateWorkflowUserTemplate: vi.fn(),
}));

const mockList = vi.mocked(listWorkflowUserTemplates);
const mockInstantiate = vi.mocked(instantiateWorkflowUserTemplate);
const mockImport = vi.mocked(importWorkflowDefinition);
const mockDelete = vi.mocked(deleteWorkflowUserTemplate);
const mockExport = vi.mocked(exportWorkflowUserTemplate);

function LocationProbe() {
  const location = useLocation();
  return (
    <div>
      <div data-testid="path">{location.pathname}</div>
      <div data-testid="state">{JSON.stringify(location.state ?? {})}</div>
    </div>
  );
}

function renderSection() {
  return render(
    <MemoryRouter initialEntries={["/workflows"]}>
      <Routes>
        <Route path="/workflows" element={<UserTemplatesSection />} />
        <Route
          path="/workflows/revisions/:revisionId/edit"
          element={<LocationProbe />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

const template = {
  template_id: "wtpl_1",
  name: "テンプレ",
  description: "説明",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
  (URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  mockList.mockResolvedValue({ items: [template] });
  mockInstantiate.mockResolvedValue({
    workflow: {} as any,
    revision: { revision_id: "wrev_new" } as any,
    validation_errors: ["Node 'x': agent が存在しません"],
  });
  mockImport.mockResolvedValue({
    workflow: {} as any,
    revision: { revision_id: "wrev_imported" } as any,
    validation_errors: [],
  });
  mockDelete.mockResolvedValue({ success: true, template_id: "wtpl_1" });
  mockExport.mockResolvedValue("{}");
});

describe("UserTemplatesSection", () => {
  it("instantiates a template and navigates to the draft with server issues", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("テンプレ");
    await user.click(screen.getByRole("button", { name: "使って作成" }));
    await waitFor(() =>
      expect(mockInstantiate).toHaveBeenCalledWith("wtpl_1", { name: "テンプレ" }),
    );
    await screen.findByTestId("path");
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/workflows/revisions/wrev_new/edit",
    );
    expect(screen.getByTestId("state")).toHaveTextContent(
      "agent が存在しません",
    );
  });

  it("imports a YAML file and navigates to the created draft", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("テンプレ");
    const file = new File(["format: x"], "definition.yaml", {
      type: "application/x-yaml",
    });
    await user.upload(screen.getByLabelText(/JSON\/YAML を import/), file);
    await waitFor(() =>
      expect(mockImport).toHaveBeenCalledWith("format: x", "yaml"),
    );
    await screen.findByTestId("path");
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/workflows/revisions/wrev_imported/edit",
    );
  });

  it("downloads a template as JSON", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("テンプレ");
    await user.click(screen.getByRole("button", { name: "JSON" }));
    await waitFor(() =>
      expect(mockExport).toHaveBeenCalledWith("wtpl_1", "json"),
    );
  });

  it("deletes a template after confirmation", async () => {
    const user = userEvent.setup();
    renderSection();
    await screen.findByText("テンプレ");
    await user.click(screen.getByRole("button", { name: "削除" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockDelete).toHaveBeenCalledWith("wtpl_1"),
    );
  });
});
