import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWorkflowRevision,
  createWorkflowUserTemplate,
  deleteWorkflow,
  deleteWorkflowRevision,
  exportWorkflowRevision,
  getWorkflow,
  listWorkflowUserTemplates,
  updateWorkflow,
  updateWorkflowUserTemplate,
} from "../../api/client";
import WorkflowDetailPage from "./WorkflowDetailPage";

vi.mock("../../api/client", () => ({
  createWorkflowRevision: vi.fn(),
  createWorkflowUserTemplate: vi.fn(),
  deleteWorkflow: vi.fn(),
  deleteWorkflowRevision: vi.fn(),
  exportWorkflowRevision: vi.fn(),
  getWorkflow: vi.fn(),
  listWorkflowUserTemplates: vi.fn(),
  updateWorkflow: vi.fn(),
  updateWorkflowUserTemplate: vi.fn(),
}));

const mockGetWorkflow = vi.mocked(getWorkflow);
const mockCreateWorkflowRevision = vi.mocked(createWorkflowRevision);
const mockDeleteWorkflowRevision = vi.mocked(deleteWorkflowRevision);
const mockUpdateWorkflow = vi.mocked(updateWorkflow);
const mockDeleteWorkflow = vi.mocked(deleteWorkflow);
const mockCreateWorkflowUserTemplate = vi.mocked(createWorkflowUserTemplate);
const mockUpdateWorkflowUserTemplate = vi.mocked(updateWorkflowUserTemplate);
const mockExportWorkflowRevision = vi.mocked(exportWorkflowRevision);
const mockListWorkflowUserTemplates = vi.mocked(listWorkflowUserTemplates);

const sampleWorkflow = {
  workflow_id: "wf_1",
  name: "テストワークフロー",
  description: "説明",
  skip_approval: false,
  revisions: [
    { revision_id: "wrev_published", version: 1, status: "published" },
    { revision_id: "wrev_draft", version: 2, status: "draft" },
  ],
  runs: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workflows/wf_1"]}>
      <Routes>
        <Route path="/workflows/:workflowId" element={<WorkflowDetailPage />} />
        <Route path="/workflows" element={<div>workflow list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  (URL as any).createObjectURL = vi.fn(() => "blob:mock");
  (URL as any).revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  mockGetWorkflow.mockResolvedValue(sampleWorkflow as any);
  mockCreateWorkflowRevision.mockResolvedValue({} as any);
  mockDeleteWorkflowRevision.mockResolvedValue({
    success: true,
    revision_id: "wrev_draft",
  });
  mockUpdateWorkflow.mockResolvedValue(sampleWorkflow as any);
  mockDeleteWorkflow.mockResolvedValue({ success: true, workflow_id: "wf_1" });
  mockCreateWorkflowUserTemplate.mockResolvedValue({} as any);
  mockUpdateWorkflowUserTemplate.mockResolvedValue({} as any);
  mockExportWorkflowRevision.mockResolvedValue("{}");
  mockListWorkflowUserTemplates.mockResolvedValue({ items: [] });
});

describe("WorkflowDetailPage revision delete", () => {
  it("shows delete buttons only for non-published revisions", async () => {
    renderPage();
    await screen.findByText("テストワークフロー");
    // Only the draft row gets a delete button; the published row does not.
    const deleteButtons = screen.getAllByRole("button", { name: "削除" });
    expect(deleteButtons).toHaveLength(1);
    expect(screen.getByRole("link", { name: "編集" })).toBeInTheDocument();
  });

  it("deletes a draft revision and reloads the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "削除" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockDeleteWorkflowRevision).toHaveBeenCalledWith("wrev_draft"),
    );
    await waitFor(() => expect(mockGetWorkflow).toHaveBeenCalledTimes(2));
  });

  it("does not delete when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    vi.mocked(window.confirm).mockReturnValue(false);
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "削除" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteWorkflowRevision).not.toHaveBeenCalled();
  });
});

describe("WorkflowDetailPage workflow update/delete", () => {
  it("renames the workflow through the edit form", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "編集" }));
    const nameInput = screen.getByLabelText("名前");
    await user.clear(nameInput);
    await user.type(nameInput, "新しい名前");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(mockUpdateWorkflow).toHaveBeenCalledWith("wf_1", {
        name: "新しい名前",
        description: "説明",
        skip_approval: false,
      }),
    );
    await waitFor(() => expect(mockGetWorkflow).toHaveBeenCalledTimes(2));
  });

  it("toggles approval skip through the edit form", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "編集" }));
    await user.click(
      screen.getByRole("checkbox", { name: "承認なしで実行する" }),
    );
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(mockUpdateWorkflow).toHaveBeenCalledWith("wf_1", {
        name: "テストワークフロー",
        description: "説明",
        skip_approval: true,
      }),
    );
  });

  it("deletes the workflow after confirmation and navigates to the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "Workflow を削除" }));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockDeleteWorkflow).toHaveBeenCalledWith("wf_1"),
    );
    await screen.findByText("workflow list");
  });

  it("does not delete the workflow when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    vi.mocked(window.confirm).mockReturnValue(false);
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "Workflow を削除" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteWorkflow).not.toHaveBeenCalled();
  });
});

describe("WorkflowDetailPage published revision actions", () => {
  it("saves a published revision as a user template", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getByRole("button", { name: "Template 保存" }));
    await waitFor(() =>
      expect(mockCreateWorkflowUserTemplate).toHaveBeenCalledWith({
        source_revision_id: "wrev_published",
        name: "テストワークフロー",
        description: "説明",
      }),
    );
  });

  it("downloads a published revision as JSON", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.click(screen.getAllByRole("button", { name: "JSON" })[0]);
    await waitFor(() =>
      expect(mockExportWorkflowRevision).toHaveBeenCalledWith(
        "wrev_published",
        "json",
      ),
    );
  });

  it("updates an existing template's content from a published revision", async () => {
    mockListWorkflowUserTemplates.mockResolvedValue({
      items: [
        {
          template_id: "wtpl_1",
          name: "既存テンプレート",
          description: "",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ],
    });
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("テストワークフロー");
    await user.selectOptions(
      screen.getByLabelText("更新するユーザーテンプレート"),
      "wtpl_1",
    );
    await user.click(screen.getByRole("button", { name: "内容を更新" }));
    await waitFor(() =>
      expect(mockUpdateWorkflowUserTemplate).toHaveBeenCalledWith("wtpl_1", {
        source_revision_id: "wrev_published",
      }),
    );
  });
});
