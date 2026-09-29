import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import WorkflowDesignerModal from "./WorkflowDesignerModal";
import * as client from "../../api/client";
import type { DesignerComposeResponse, WorkflowDetail } from "../../api/types";

vi.mock("../../api/client", async () => {
  const actual = await vi.importActual("../../api/client");
  return {
    ...actual,
    composeDesignerWorkflow: vi.fn(),
    importWorkflowDefinition: vi.fn(),
  };
});

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: vi.fn(),
  };
});

describe("WorkflowDesignerModal", () => {
  const mockNavigate = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useNavigate).mockReturnValue(mockNavigate);
  });

  it("does not render when isOpen is false", () => {
    render(
      <MemoryRouter>
        <WorkflowDesignerModal isOpen={false} onClose={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.queryByText("AIで下書きを作成 (Workflow Designer)")).toBeNull();
  });

  it("renders requirement input form and handles compose flow with draft creation", async () => {
    const mockComposeResponse: DesignerComposeResponse = {
      package: {
        format: "obsidian-ai-hub.workflow-definition",
        version: 1,
        name: "Test Draft",
        description: "Test description",
        inputs_schema: { type: "object" },
        nodes: [],
        edges: [],
      },
      summary: "Generated summary",
      assumptions: ["Assumption 1"],
      node_analysis: [
        {
          node_id: "node_1",
          node_type: "capability",
          label: "Read Note",
          effects: "Read only",
          requires_approval: false,
          requires_approval_reason: "Auto approved",
        },
      ],
      structural_errors: [],
      validation_issues: [
        { code: "graph_issue", message: "Static validation notice" },
      ],
    };

    vi.mocked(client.composeDesignerWorkflow).mockResolvedValue(mockComposeResponse);
    vi.mocked(client.importWorkflowDefinition).mockResolvedValue({
      workflow: {
        workflow_id: "wf_1",
        name: "Test Draft",
        description: "Test description",
        skip_approval: false,
        created_at: "2026-09-28T00:00:00Z",
        updated_at: "2026-09-28T00:00:00Z",
      } as WorkflowDetail,
      revision: { revision_id: "wrev_123", revision_number: 1, status: "draft" } as any,
      validation_errors: ["Static validation notice"],
    });

    const handleClose = vi.fn();

    render(
      <MemoryRouter>
        <WorkflowDesignerModal isOpen={true} onClose={handleClose} />
      </MemoryRouter>
    );

    expect(screen.getByText("AIで下書きを作成 (Workflow Designer)")).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText(/Vault 内の daily ノート/);
    fireEvent.change(textarea, { target: { value: "Create a note reader workflow" } });

    const startBtn = screen.getByText("AI で生成開始");
    fireEvent.click(startBtn);

    await waitFor(() => {
      expect(client.composeDesignerWorkflow).toHaveBeenCalledWith("Create a note reader workflow", expect.any(AbortSignal));
    });

    await waitFor(() => {
      expect(screen.getByText("Generated summary")).toBeInTheDocument();
      expect(screen.getByText("Assumption 1")).toBeInTheDocument();
      expect(screen.getByText("Read Note (capability)")).toBeInTheDocument();
      expect(screen.getByText("Static validation notice")).toBeInTheDocument();
    });

    const createDraftBtn = screen.getByText("下書きを作成");
    expect(createDraftBtn).not.toBeDisabled();

    fireEvent.click(createDraftBtn);

    await waitFor(() => {
      expect(client.importWorkflowDefinition).toHaveBeenCalled();
      expect(mockNavigate).toHaveBeenCalledWith("/workflows/revisions/wrev_123/edit");
      expect(handleClose).toHaveBeenCalled();
    });
  });

  it("disables import button when structural errors exist", async () => {
    const mockErrorResponse: DesignerComposeResponse = {
      package: null,
      summary: null,
      assumptions: [],
      node_analysis: [],
      structural_errors: [{ code: "structural_error", message: "Duplicate node_id" }],
      validation_issues: [],
    };

    vi.mocked(client.composeDesignerWorkflow).mockResolvedValue(mockErrorResponse);

    render(
      <MemoryRouter>
        <WorkflowDesignerModal isOpen={true} onClose={vi.fn()} />
      </MemoryRouter>
    );

    const textarea = screen.getByPlaceholderText(/Vault 内の daily ノート/);
    fireEvent.change(textarea, { target: { value: "Broken graph" } });

    fireEvent.click(screen.getByText("AI で生成開始"));

    await waitFor(() => {
      expect(screen.getByText("Duplicate node_id")).toBeInTheDocument();
    });

    const createDraftBtn = screen.getByText("下書きを作成");
    expect(createDraftBtn).toBeDisabled();
  });

  it("does not call import after aborting the compose request", async () => {
    vi.mocked(client.composeDesignerWorkflow).mockImplementation(
      (_req: string, signal?: AbortSignal) =>
        new Promise<DesignerComposeResponse>((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            const abortErr = new Error("aborted");
            abortErr.name = "AbortError";
            reject(abortErr);
          });
        })
    );

    render(
      <MemoryRouter>
        <WorkflowDesignerModal isOpen={true} onClose={vi.fn()} />
      </MemoryRouter>
    );

    const textarea = screen.getByPlaceholderText(/Vault 内の daily ノート/);
    fireEvent.change(textarea, { target: { value: "Something slow" } });
    fireEvent.click(screen.getByText("AI で生成開始"));

    await waitFor(() => {
      expect(screen.getByText("表示中止")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("表示中止"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/Vault 内の daily ノート/)).toBeInTheDocument();
    });
    expect(client.importWorkflowDefinition).not.toHaveBeenCalled();
    expect(screen.queryByText("下書きを作成")).toBeNull();
  });
});
