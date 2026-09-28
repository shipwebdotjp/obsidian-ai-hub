import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteWorkflowRun,
  getMediaBlob,
  getWorkflow,
  getWorkflowRun,
} from "../../api/client";
import { subscribeRunEvents } from "../../api/runSse";
import type { WorkflowRun, WorkflowRunNode } from "../../api/types";
import WorkflowRunPage from "./WorkflowRunPage";

vi.mock("../../api/client", () => ({
  approveWorkflowRun: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  deleteWorkflowRun: vi.fn(),
  getMediaBlob: vi.fn(),
  getWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  rerunWorkflowRun: vi.fn(),
  resolveWorkflowAttention: vi.fn(),
  resumeWorkflowRun: vi.fn(),
  updateWorkflow: vi.fn(),
}));

vi.mock("../../api/runSse", () => ({
  loadLastAppliedId: vi.fn(() => 0),
  saveLastAppliedId: vi.fn(),
  subscribeRunEvents: vi.fn(),
}));

const mockGetWorkflowRun = vi.mocked(getWorkflowRun);
const mockGetWorkflow = vi.mocked(getWorkflow);
const mockDeleteWorkflowRun = vi.mocked(deleteWorkflowRun);
const mockSubscribeRunEvents = vi.mocked(subscribeRunEvents);

const graphNodes = [
  {
    node_id: "node-a",
    node_type: "capability" as const,
    label: "取得",
    config: { capability_key: "vault_search", inputs: {} },
    parent_loop_node_id: null,
    ui_position: { x: 40, y: 40 },
  },
  {
    node_id: "node-b",
    node_type: "agent" as const,
    label: "要約",
    config: { agent_id: "agent_1", inputs: {} },
    parent_loop_node_id: null,
    ui_position: { x: 260, y: 40 },
  },
  {
    node_id: "node-c",
    node_type: "terminal" as const,
    label: "完了",
    config: { outcome: "success" },
    parent_loop_node_id: null,
    ui_position: { x: 480, y: 40 },
  },
];

const graphEdges = [
  {
    edge_id: "edge-1",
    source_node_id: "node-a",
    target_node_id: "node-b",
    edge_kind: "normal" as const,
    condition: null,
    order_index: 0,
  },
  {
    edge_id: "edge-2",
    source_node_id: "node-b",
    target_node_id: "node-c",
    edge_kind: "normal" as const,
    condition: null,
    order_index: 0,
  },
];

function row(
  nodeId: string,
  activationId: string,
  attempt: number,
  status: WorkflowRunNode["status"],
  startedAt: string,
  output?: string,
): WorkflowRunNode {
  return {
    run_id: "wrun_1",
    node_id: nodeId,
    activation_id: activationId,
    attempt,
    status,
    output_json: output ?? null,
    started_at: startedAt,
    finished_at: null,
  };
}

const runningRows = [
  row("node-a", "act-a1", 1, "failed", "2026-09-21T00:00:01Z", "output-a-retry"),
  row("node-a", "act-a1", 2, "succeeded", "2026-09-21T00:00:02Z", "output-a"),
  row("node-b", "act-b1", 1, "needs_attention", "2026-09-21T00:00:03Z"),
  row("node-b", "act-b2", 1, "succeeded", "2026-09-21T00:00:04Z", "output-b"),
];

function baseRun(overrides: Partial<WorkflowRun>): WorkflowRun {
  return {
    run_id: "wrun_1",
    workflow_id: "wf_1",
    revision_id: "wrev_1",
    status: "running",
    inputs: {},
    created_at: "2026-09-21T00:00:00Z",
    updated_at: "2026-09-21T00:00:05Z",
    ...overrides,
  };
}

const runningRun = baseRun({
  graph_snapshot: { inputs_schema: { type: "object" }, nodes: graphNodes, edges: graphEdges },
  nodes: runningRows,
  events: [],
});

const legacyRun = baseRun({
  status: "completed",
  graph_snapshot: null,
  nodes: [
    row("node-a", "act-a1", 1, "succeeded", "2026-09-21T00:00:01Z", "output-a"),
    row("node-b", "act-b1", 1, "succeeded", "2026-09-21T00:00:02Z", "output-b"),
  ],
  events: [],
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workflows/runs/wrun_1"]}>
      <Routes>
        <Route path="/workflows/runs/:runId" element={<WorkflowRunPage />} />
        <Route path="/workflows" element={<div>workflow list</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  mockSubscribeRunEvents.mockResolvedValue(undefined);
  mockGetWorkflowRun.mockResolvedValue(runningRun);
  mockGetWorkflow.mockResolvedValue({
    workflow_id: "wf_1",
    name: "テストWF",
    description: "",
    skip_approval: false,
  } as never);
  mockDeleteWorkflowRun.mockResolvedValue({ success: true, run_id: "wrun_1" });
});

describe("WorkflowRunPage run delete", () => {
  it("shows the delete button for terminal runs", async () => {
    mockGetWorkflowRun.mockResolvedValue(legacyRun);
    renderPage();
    await screen.findByTestId("run-status");
    expect(screen.getByTestId("run-delete")).toBeInTheDocument();
  });

  it("hides the delete button for non-terminal runs", async () => {
    renderPage();
    await screen.findByTestId("run-status");
    expect(screen.queryByTestId("run-delete")).not.toBeInTheDocument();
  });

  it("deletes a terminal run after confirmation and returns to the list", async () => {
    const user = userEvent.setup();
    mockGetWorkflowRun.mockResolvedValue(legacyRun);
    renderPage();
    await screen.findByTestId("run-status");
    await user.click(screen.getByTestId("run-delete"));
    expect(window.confirm).toHaveBeenCalled();
    await waitFor(() =>
      expect(mockDeleteWorkflowRun).toHaveBeenCalledWith("wrun_1"),
    );
    await screen.findByText("workflow list");
  });
});

describe("WorkflowRunPage child run summary", () => {
  it("shows tool call counts for an agent child run", async () => {
    mockGetWorkflowRun.mockResolvedValue(
      baseRun({
        status: "completed",
        graph_snapshot: null,
        nodes: [
          {
            ...row("node-b", "act-b1", 1, "succeeded", "2026-09-21T00:00:02Z"),
            child_kind: "agent",
            child_run_id: "arun_1",
            child_run: {
              run_id: "arun_1",
              status: "succeeded",
              tool_calls: [
                { tool_name: "vault_search", count: 2 },
                { tool_name: "vault_read_file", count: 1 },
              ],
            },
          },
        ],
        events: [],
      }),
    );
    renderPage();
    const tools = await screen.findByTestId("run-node-child-tools-act-b1");
    expect(within(tools).getByText("vault_search ×2")).toBeInTheDocument();
    expect(within(tools).getByText("vault_read_file ×1")).toBeInTheDocument();
  });
});

describe("WorkflowRunPage run graph", () => {
  it("shows aggregated node states and preselects the last executed node", async () => {
    renderPage();
    await screen.findByTestId("workflow-canvas");

    // Retry resolved to the last attempt; an older needs_attention row stays
    // behind the newer succeeded activation.
    expect(screen.getByTestId("workflow-node-node-a")).toHaveAttribute(
      "data-status",
      "succeeded",
    );
    expect(screen.getByTestId("workflow-node-node-b")).toHaveAttribute(
      "data-status",
      "succeeded",
    );
    expect(screen.getByTestId("workflow-node-node-b")).toHaveAttribute(
      "data-activation-count",
      "2",
    );
    expect(screen.getByTestId("workflow-node-count-node-b")).toBeInTheDocument();
    expect(screen.getByTestId("workflow-node-node-c")).toHaveAttribute(
      "data-status",
      "unexecuted",
    );

    // No pending or resolved-attention node: the last executed node is shown.
    expect(await screen.findByTestId("run-node-detail")).toHaveTextContent(
      "node-b",
    );

    // The node table is filtered to the selected node's history.
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("output-b")).toBeInTheDocument();
    expect(within(table).queryByText("output-a")).not.toBeInTheDocument();
  });

  it("filters the node history to the clicked graph node", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("workflow-canvas");

    await user.click(screen.getByTestId("workflow-node-node-a"));

    expect(screen.getByTestId("run-node-detail")).toHaveTextContent("node-a");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("output-a")).toBeInTheDocument();
    expect(within(table).getByText("output-a-retry")).toBeInTheDocument();
    expect(within(table).queryByText("output-b")).not.toBeInTheDocument();
  });

  it("shows an empty state for an unexecuted node and clears the filter", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("workflow-canvas");

    await user.click(screen.getByTestId("workflow-node-node-c"));

    // Unexecuted nodes have no history rows.
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByTestId("run-node-empty")).toBeInTheDocument();

    await user.click(screen.getByTestId("run-graph-clear-selection"));

    // Back to the unfiltered history of both nodes.
    expect(screen.queryByTestId("run-node-empty")).not.toBeInTheDocument();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByText("output-a")).toBeInTheDocument();
    expect(within(table).getByText("output-b")).toBeInTheDocument();
  });

  it("updates node states after an SSE envelope triggers a reload", async () => {
    renderPage();
    await screen.findByTestId("workflow-canvas");
    expect(screen.getByTestId("workflow-node-node-c")).toHaveAttribute(
      "data-status",
      "unexecuted",
    );

    mockGetWorkflowRun.mockResolvedValue(
      baseRun({
        status: "completed",
        graph_snapshot: {
          inputs_schema: { type: "object" },
          nodes: graphNodes,
          edges: graphEdges,
        },
        nodes: [
          ...runningRows,
          row("node-c", "act-c1", 1, "succeeded", "2026-09-21T00:00:05Z"),
        ],
        events: [],
      }),
    );
    const options =
      mockSubscribeRunEvents.mock.calls.at(-1)?.[0];
    expect(options?.onEnvelope).toBeDefined();
    act(() => {
      options?.onEnvelope?.({ eventId: 9, data: {} });
    });

    await waitFor(
      () =>
        expect(screen.getByTestId("workflow-node-node-c")).toHaveAttribute(
          "data-status",
          "succeeded",
        ),
      { timeout: 3000 },
    );
  });

  it("shows 停止要求中 for a cancelling run", async () => {
    mockGetWorkflowRun.mockResolvedValue(
      baseRun({ status: "cancelling", nodes: [], events: [] }),
    );
    renderPage();
    expect(await screen.findByTestId("run-status")).toHaveTextContent(
      "停止要求中",
    );
  });

  it("shows the cancel attention reason and a child run link", async () => {
    mockGetWorkflowRun.mockResolvedValue(
      baseRun({
        status: "waiting_attention",
        graph_snapshot: {
          inputs_schema: { type: "object" },
          nodes: graphNodes,
          edges: graphEdges,
        },
        nodes: [
          {
            ...row(
              "node-a",
              "act-a1",
              1,
              "needs_attention",
              "2026-09-21T00:00:03Z",
            ),
            child_kind: "research",
            child_run_id: "job_42",
            attention_reason: "cancel_with_unknown_external_result",
          },
        ],
        events: [],
      }),
    );
    renderPage();

    const banner = await screen.findByTestId("run-attention-banner");
    expect(banner).toHaveTextContent("外部処理の結果を確認できません");
    expect(banner).toHaveTextContent("job_42");
    expect(within(banner).getByRole("link", { name: "確認する" })).toHaveAttribute(
      "href",
      "/research",
    );
  });

});

describe("WorkflowRunPage node inputs/outputs", () => {
  function ioRow(
    activationId: string,
    overrides: Partial<WorkflowRunNode> = {},
  ): WorkflowRunNode {
    return {
      run_id: "wrun_1",
      node_id: "node-a",
      activation_id: activationId,
      attempt: 1,
      status: "succeeded",
      started_at: "2026-09-21T00:00:01Z",
      finished_at: null,
      ...overrides,
    };
  }

  function ioRun(nodes: WorkflowRunNode[]): WorkflowRun {
    return baseRun({ status: "completed", graph_snapshot: null, nodes, events: [] });
  }

  async function openDetails(testId: string) {
    const user = userEvent.setup();
    const details = (await screen.findByTestId(testId)) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    await user.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);
    return details;
  }

  it("starts closed and reveals the full stored input and output on expand", async () => {
    const inputs = '{"prompt":"hello"}';
    const output = '{"answer":42,"items":[1,2]}';
    mockGetWorkflowRun.mockResolvedValue(
      ioRun([ioRow("act-io1", { inputs_json: inputs, output_json: output })]),
    );
    renderPage();

    const details = (await screen.findByTestId(
      "run-node-io-act-io1-1",
    )) as HTMLDetailsElement;
    expect(details.open).toBe(false);
    // Closed preview shows the character counts without hover.
    expect(details).toHaveTextContent(`入力 ${inputs.length}文字`);
    expect(details).toHaveTextContent(`出力 ${output.length}文字`);
    // Full values are not rendered until expanded (single closed preview match).
    expect(screen.queryByTestId("run-node-io-act-io1-1-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId("run-node-io-act-io1-1-output")).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(details.querySelector("summary")!);
    expect(details.open).toBe(true);

    // JSON values are pretty-printed in full (textContent: toHaveTextContent
    // normalizes whitespace).
    expect(screen.getByTestId("run-node-io-act-io1-1-input").textContent).toBe(
      JSON.stringify(JSON.parse(inputs), null, 2),
    );
    const outputPre = screen.getByTestId("run-node-io-act-io1-1-output");
    expect(outputPre.textContent).toBe(
      JSON.stringify(JSON.parse(output), null, 2),
    );
    expect(screen.queryByTestId("run-node-io-act-io1-1-error")).not.toBeInTheDocument();
  });

  it("shows a non-JSON value as-is and an error-only node without input/output sections", async () => {
    mockGetWorkflowRun.mockResolvedValue(
      ioRun([
        ioRow("act-plain", { output_json: "just plain text" }),
        ioRow("act-err", {
          output_json: null,
          inputs_json: null,
          status: "failed",
          error_summary: "boom failed",
        }),
      ]),
    );
    renderPage();

    await openDetails("run-node-io-act-plain-1");
    expect(screen.getByTestId("run-node-io-act-plain-1-output")).toHaveTextContent(
      "just plain text",
    );
    expect(
      screen.queryByTestId("run-node-io-act-plain-1-input"),
    ).not.toBeInTheDocument();

    await openDetails("run-node-io-act-err-1");
    expect(screen.getByTestId("run-node-io-act-err-1-error")).toHaveTextContent(
      "boom failed",
    );
    expect(screen.queryByTestId("run-node-io-act-err-1-input")).not.toBeInTheDocument();
    expect(screen.queryByTestId("run-node-io-act-err-1-output")).not.toBeInTheDocument();

    // Independent rows stay open together for comparing upstream/downstream values.
    expect(
      (screen.getByTestId("run-node-io-act-plain-1") as HTMLDetailsElement).open,
    ).toBe(true);
    expect(
      (screen.getByTestId("run-node-io-act-err-1") as HTMLDetailsElement).open,
    ).toBe(true);
  });

  it("reveals a long value in full without truncation", async () => {
    const longOutput = `{"text":"${"x".repeat(500)}"}`;
    mockGetWorkflowRun.mockResolvedValue(
      ioRun([ioRow("act-long", { output_json: longOutput })]),
    );
    renderPage();

    const details = (await screen.findByTestId(
      "run-node-io-act-long-1",
    )) as HTMLDetailsElement;
    // Closed preview is shortened.
    expect(details.textContent!.length).toBeLessThan(longOutput.length);

    const user = userEvent.setup();
    await user.click(details.querySelector("summary")!);
    expect(screen.getByTestId("run-node-io-act-long-1-output").textContent).toBe(
      JSON.stringify(JSON.parse(longOutput), null, 2),
    );
  });

  it("keeps generated media cards visible in the row while I/O is collapsed", async () => {
    vi.mocked(getMediaBlob).mockResolvedValue(
      new Blob(["x"], { type: "image/png" }),
    );
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL: vi.fn(() => "blob:media"),
      revokeObjectURL: vi.fn(),
    });
    try {
      mockGetWorkflowRun.mockResolvedValue(
        ioRun([
          ioRow("act-media", {
            inputs_json: '{"prompt":"a cat"}',
            output_json:
              '{"media_id":"m1","media_type":"image","mime_type":"image/png"}',
          }),
        ]),
      );
      renderPage();

      await screen.findByTestId("run-node-io-act-media-1");
      expect(screen.getByTestId("generated-media-list")).toBeInTheDocument();
      expect(
        (screen.getByTestId("run-node-io-act-media-1") as HTMLDetailsElement).open,
      ).toBe(false);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("WorkflowRunPage legacy run history", () => {
  it("shows the full node history without a graph for legacy runs", async () => {
    mockGetWorkflowRun.mockResolvedValue(legacyRun);
    renderPage();
    await screen.findByText("概要");

    expect(screen.queryByTestId("workflow-canvas")).not.toBeInTheDocument();
    expect(screen.queryByTestId("run-node-detail")).not.toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("output-a")).toBeInTheDocument();
    expect(within(table).getByText("output-b")).toBeInTheDocument();
  });
});
