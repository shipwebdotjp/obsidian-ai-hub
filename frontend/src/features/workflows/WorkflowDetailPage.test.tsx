import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createWorkflowRevision,
  createWorkflowRun,
  createWorkflowUserTemplate,
  deleteWorkflow,
  deleteWorkflowRevision,
  deleteWorkflowRun,
  exportWorkflowRevision,
  getWorkflow,
  listWorkflowUserTemplates,
  updateWorkflow,
  updateWorkflowUserTemplate,
} from "../../api/client";
import WorkflowDetailPage from "./WorkflowDetailPage";

vi.mock("../../api/client", () => ({
  createWorkflowRevision: vi.fn(),
  createWorkflowRun: vi.fn(),
  createWorkflowUserTemplate: vi.fn(),
  deleteWorkflow: vi.fn(),
  deleteWorkflowRevision: vi.fn(),
  deleteWorkflowRun: vi.fn(),
  exportWorkflowRevision: vi.fn(),
  getWorkflow: vi.fn(),
  listWorkflowUserTemplates: vi.fn(),
  updateWorkflow: vi.fn(),
  updateWorkflowUserTemplate: vi.fn(),
}));

const mockGetWorkflow = vi.mocked(getWorkflow);
const mockCreateWorkflowRevision = vi.mocked(createWorkflowRevision);
const mockCreateWorkflowRun = vi.mocked(createWorkflowRun);
const mockDeleteWorkflowRevision = vi.mocked(deleteWorkflowRevision);
const mockDeleteWorkflowRun = vi.mocked(deleteWorkflowRun);
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
    {
      revision_id: "wrev_published",
      version: 1,
      status: "published",
      inputs_schema: { type: "object" },
    },
    {
      revision_id: "wrev_draft",
      version: 2,
      status: "draft",
      inputs_schema: { type: "object" },
    },
  ],
  runs: [],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workflows/wf_1"]}>
      <Routes>
        <Route path="/workflows/:workflowId" element={<WorkflowDetailPage />} />
        <Route path="/workflows" element={<div>workflow list</div>} />
        <Route
          path="/workflows/revisions/:revisionId/edit"
          element={<div>editor</div>}
        />
        <Route path="/workflows/runs/:runId" element={<div>run page</div>} />
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
  mockCreateWorkflowRun.mockResolvedValue({ run_id: "wrun_new" } as any);
  mockDeleteWorkflowRevision.mockResolvedValue({
    success: true,
    revision_id: "wrev_draft",
  });
  mockDeleteWorkflowRun.mockResolvedValue({ success: true, run_id: "wrun_done" });
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
    // Only the draft row gets a delete button; the published row does not.
    const deleteButtons = screen.getAllByRole("button", { name: "削除" });
    expect(deleteButtons).toHaveLength(1);
    expect(screen.getByRole("link", { name: "編集" })).toBeInTheDocument();
  });

  it("deletes a draft revision and reloads the list", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByRole("button", { name: "削除" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteWorkflowRevision).not.toHaveBeenCalled();
  });
});

describe("WorkflowDetailPage run delete", () => {
  const runWorkflow = {
    ...sampleWorkflow,
    revisions: [],
    runs: [
      {
        run_id: "wrun_done",
        status: "completed",
        created_at: "2026-09-25T00:00:00+00:00",
      },
      {
        run_id: "wrun_running",
        status: "running",
        created_at: "2026-09-25T00:00:00+00:00",
      },
    ],
  };

  it("shows the delete button only for terminal runs", async () => {
    mockGetWorkflow.mockResolvedValue(runWorkflow as any);
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    expect(screen.getAllByTestId(/^run-delete-/)).toHaveLength(1);
  });

  it("deletes a terminal run after confirmation and reloads", async () => {
    const user = userEvent.setup();
    mockGetWorkflow.mockResolvedValue(runWorkflow as any);
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByTestId("run-delete-wrun_done"));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockDeleteWorkflowRun).toHaveBeenCalledWith("wrun_done"),
    );
    await waitFor(() => expect(mockGetWorkflow).toHaveBeenCalledTimes(2));
  });

  it("does not delete a run when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    vi.mocked(window.confirm).mockReturnValue(false);
    mockGetWorkflow.mockResolvedValue(runWorkflow as any);
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByTestId("run-delete-wrun_done"));
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteWorkflowRun).not.toHaveBeenCalled();
  });
});

describe("WorkflowDetailPage workflow update/delete", () => {
  it("renames the workflow through the edit form", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByRole("button", { name: "Workflow を削除" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteWorkflow).not.toHaveBeenCalled();
  });
});

describe("WorkflowDetailPage published revision actions", () => {
  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(screen.getByTestId("revision-menu"));
  }

  it("saves a published revision as a user template from the menu", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await openMenu(user);
    await user.click(screen.getByTestId("menu-save-template"));
    await waitFor(() =>
      expect(mockCreateWorkflowUserTemplate).toHaveBeenCalledWith({
        source_revision_id: "wrev_published",
        name: "テストワークフロー",
        description: "説明",
      }),
    );
  });

  it("downloads a published revision as JSON from the menu", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await openMenu(user);
    await user.click(screen.getByTestId("menu-download-json"));
    await waitFor(() =>
      expect(mockExportWorkflowRevision).toHaveBeenCalledWith(
        "wrev_published",
        "json",
      ),
    );
  });

  it("updates an existing template's content through the dialog", async () => {
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
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await openMenu(user);
    await user.click(screen.getByTestId("menu-update-template"));
    await user.selectOptions(
      screen.getByLabelText("更新するユーザーテンプレート"),
      "wtpl_1",
    );
    await user.click(screen.getByTestId("template-update-confirm"));
    await waitFor(() =>
      expect(mockUpdateWorkflowUserTemplate).toHaveBeenCalledWith("wtpl_1", {
        source_revision_id: "wrev_published",
      }),
    );
  });
});

describe("WorkflowDetailPage run from published revision", () => {
  it("opens the run form and starts a run, then navigates to it", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByTestId("run-form-toggle"));
    await user.click(screen.getByTestId("run-start"));
    await waitFor(() =>
      expect(mockCreateWorkflowRun).toHaveBeenCalledWith("wrev_published", {}),
    );
    await screen.findByText("run page");
  });

  it("offers no run action when nothing is published", async () => {
    mockGetWorkflow.mockResolvedValue({
      ...sampleWorkflow,
      revisions: [sampleWorkflow.revisions[1]],
    } as any);
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    expect(screen.queryByTestId("run-form-toggle")).not.toBeInTheDocument();
  });
});

describe("WorkflowDetailPage navigation", () => {
  it("navigates to the editor after creating a draft", async () => {
    mockCreateWorkflowRevision.mockResolvedValue({
      revision_id: "wrev_new",
    } as any);
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    await user.click(screen.getByRole("button", { name: "新しい下書き" }));
    await waitFor(() =>
      expect(mockCreateWorkflowRevision).toHaveBeenCalledWith("wf_1"),
    );
    await screen.findByText("editor");
  });

  it("links back to the workflow list from the breadcrumb", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    const nav = screen.getByRole("navigation");
    const backLink = nav.querySelector('a[href="/workflows"]');
    expect(backLink).not.toBeNull();
    await user.click(backLink as Element);
    await screen.findByText("workflow list");
  });
});

describe("WorkflowDetailPage old revisions", () => {
  const workflowWithOld = {
    ...sampleWorkflow,
    revisions: [
      ...sampleWorkflow.revisions,
      {
        revision_id: "wrev_old",
        version: 0,
        status: "superseded",
        inputs_schema: { type: "object" },
      },
    ],
  };

  it("collapses superseded revisions until toggled", async () => {
    mockGetWorkflow.mockResolvedValue(workflowWithOld as any);
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "テストワークフロー" });
    expect(screen.getByTestId("old-revisions-toggle")).toBeInTheDocument();
    // The old revision's delete button appears only after expanding.
    expect(screen.getAllByRole("button", { name: "削除" })).toHaveLength(1);
    await user.click(screen.getByTestId("old-revisions-toggle"));
    expect(screen.getAllByRole("button", { name: "削除" })).toHaveLength(2);
  });
});
