import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWorkflowRevision,
  deleteWorkflow,
  deleteWorkflowRevision,
  getWorkflow,
  updateWorkflow,
} from "../../api/client";
import WorkflowDetailPage from "./WorkflowDetailPage";

vi.mock("../../api/client", () => ({
  createWorkflowRevision: vi.fn(),
  deleteWorkflow: vi.fn(),
  deleteWorkflowRevision: vi.fn(),
  getWorkflow: vi.fn(),
  updateWorkflow: vi.fn(),
}));

const mockGetWorkflow = vi.mocked(getWorkflow);
const mockCreateWorkflowRevision = vi.mocked(createWorkflowRevision);
const mockDeleteWorkflowRevision = vi.mocked(deleteWorkflowRevision);
const mockUpdateWorkflow = vi.mocked(updateWorkflow);
const mockDeleteWorkflow = vi.mocked(deleteWorkflow);

const sampleWorkflow = {
  workflow_id: "wf_1",
  name: "テストワークフロー",
  description: "説明",
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
  mockGetWorkflow.mockResolvedValue(sampleWorkflow as any);
  mockCreateWorkflowRevision.mockResolvedValue({} as any);
  mockDeleteWorkflowRevision.mockResolvedValue({
    success: true,
    revision_id: "wrev_draft",
  });
  mockUpdateWorkflow.mockResolvedValue(sampleWorkflow as any);
  mockDeleteWorkflow.mockResolvedValue({ success: true, workflow_id: "wf_1" });
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
      }),
    );
    await waitFor(() => expect(mockGetWorkflow).toHaveBeenCalledTimes(2));
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
