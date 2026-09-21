import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWorkflowRevision,
  deleteWorkflowRevision,
  getWorkflow,
} from "../../api/client";
import WorkflowDetailPage from "./WorkflowDetailPage";

vi.mock("../../api/client", () => ({
  createWorkflowRevision: vi.fn(),
  deleteWorkflowRevision: vi.fn(),
  getWorkflow: vi.fn(),
}));

const mockGetWorkflow = vi.mocked(getWorkflow);
const mockCreateWorkflowRevision = vi.mocked(createWorkflowRevision);
const mockDeleteWorkflowRevision = vi.mocked(deleteWorkflowRevision);

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
