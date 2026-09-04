import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AgentsPage from "../AgentsPage";

vi.mock("../../../api/client", () => ({
  listAgents: vi.fn(),
  listAgentTools: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  listAgentSessions: vi.fn(),
  searchAgentMessages: vi.fn(),
  createAgentSession: vi.fn(),
  getAgentSessionDetail: vi.fn(),
  deleteAgentSession: vi.fn(),
  listPromptTemplates: vi.fn(),
  createPromptTemplate: vi.fn(),
  updatePromptTemplate: vi.fn(),
  deletePromptTemplate: vi.fn(),
  updateAgentSession: vi.fn(),
  startAgentRun: vi.fn(),
  cancelAgentRun: vi.fn(),
  subscribeAgentRunEvents: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

vi.mock("../../../api/runSse", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/runSse")>();
  return { ...actual, loadLastAppliedId: vi.fn(() => 0), saveLastAppliedId: vi.fn() };
});

import {
  listAgents,
  listAgentTools,
  listAgentSessions,
  searchAgentMessages,
  getAgentSessionDetail,
  listPromptTemplates,
  startAgentRun,
  cancelAgentRun,
  subscribeAgentRunEvents,
} from "../../../api/client";
import { loadLastAppliedId, saveLastAppliedId } from "../../../api/runSse";

const mockListAgents = vi.mocked(listAgents);
const mockListTools = vi.mocked(listAgentTools);
const mockListSessions = vi.mocked(listAgentSessions);
const mockGetDetail = vi.mocked(getAgentSessionDetail);
const mockListTemplates = vi.mocked(listPromptTemplates);
const mockStart = vi.mocked(startAgentRun);
const mockSubscribe = vi.mocked(subscribeAgentRunEvents);
const mockCancel = vi.mocked(cancelAgentRun);

const agent = {
  agent_id: "agent_123",
  name: "A",
  system_prompt: "P",
  provider: null,
  model: null,
  tool_ids: [],
  created_at: "",
  updated_at: "",
};
const session = {
  session_id: "asess_456",
  agent_id: "agent_123",
  title: "S",
  created_at: "",
  updated_at: "",
};

beforeEach(() => {
  vi.clearAllMocks();
  mockStart.mockReset();
  mockSubscribe.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  mockListAgents.mockResolvedValue({ agents: [agent] });
  mockListTools.mockResolvedValue({ tools: [] });
  mockListSessions.mockResolvedValue({ sessions: [session] });
  vi.mocked(searchAgentMessages).mockResolvedValue({ results: [] });
  mockListTemplates.mockResolvedValue({ templates: [] });
  mockGetDetail.mockResolvedValue({
    session,
    agent,
    messages: [],
    runs: [],
  });
  mockStart.mockResolvedValue({
    run: {
      run_id: "arun_new",
      session_id: session.session_id,
      user_message_id: "u1",
      assistant_message_id: null,
      status: "queued",
      hitl_run_id: null,
      used_tools: [],
      created_hitl_run_ids: [],
      error_message: null,
      started_at: "",
      finished_at: null,
    },
  });
  mockSubscribe.mockImplementation(async () => {});
});

describe("AgentsPage run-SSE", () => {
  it("starts then subscribes immediately and folds text_append without duplication", async () => {
    const user = userEvent.setup();
    mockSubscribe.mockImplementation(async (_rid, opts) => {
      const onEnvelope = (opts as { onEnvelope: (e: unknown) => void }).onEnvelope;
      onEnvelope({ eventId: 1, data: { type: "text_append", delta: "hello " } });
      onEnvelope({ eventId: 1, data: { type: "text_append", delta: "hello " } });
      onEnvelope({ eventId: 2, data: { type: "text_append", delta: "world" } });
      onEnvelope({
        eventId: 3,
        data: {
          type: "done",
          message: {
            message_id: "m3",
            session_id: session.session_id,
            sequence: 3,
            role: "assistant",
            content: "hello world",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_new",
            session_id: session.session_id,
            user_message_id: "u1",
            assistant_message_id: "m3",
            status: "succeeded",
            hitl_run_id: null,
            used_tools: [],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
        },
      });
    });
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "hi");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalled());
    await waitFor(() => expect(mockSubscribe).toHaveBeenCalled());
    // Duplicate eventId 1 ignored: storage saved with 1,2,3 in order.
    await waitFor(() =>
      expect(vi.mocked(saveLastAppliedId)).toHaveBeenCalledWith("agent", "arun_new", 2),
    );
  });

  it("unmount/session-switch aborts subscription only and never cancels the run", async () => {
    const user = userEvent.setup();
    let capturedSignal: AbortSignal | undefined;
    mockSubscribe.mockImplementation(async (_rid, opts) => {
      capturedSignal = (opts as { signal?: AbortSignal }).signal;
      // Hang until aborted (simulates live run).
      await new Promise<void>((resolve) => {
        capturedSignal?.addEventListener("abort", () => resolve(), { once: true });
      });
    });
    const { unmount } = render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "long task");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockSubscribe).toHaveBeenCalled());
    expect(capturedSignal?.aborted).toBe(false);
    unmount();
    expect(capturedSignal?.aborted).toBe(true);
    expect(mockCancel).not.toHaveBeenCalled();
  });

  it("restores active run on reload by replaying from cached last-event-id", async () => {
    vi.mocked(loadLastAppliedId).mockReturnValue(2);
    mockGetDetail.mockResolvedValue({
      session,
      agent,
      messages: [],
      runs: [
        {
          run_id: "arun_active",
          session_id: session.session_id,
          user_message_id: "u1",
          assistant_message_id: null,
          status: "running",
          hitl_run_id: null,
          used_tools: [],
          created_hitl_run_ids: [],
          error_message: null,
          started_at: "",
          finished_at: null,
        },
      ],
      active_run: {
        run_id: "arun_active",
        session_id: session.session_id,
        user_message_id: "u1",
        assistant_message_id: null,
        status: "running",
        hitl_run_id: null,
        used_tools: [],
        created_hitl_run_ids: [],
        error_message: null,
        started_at: "",
        finished_at: null,
      },
    });
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(mockSubscribe).toHaveBeenCalled());
    const call = mockSubscribe.mock.calls[0];
    expect(call[0]).toBe("arun_active");
    expect((call[1] as { lastEventId: number }).lastEventId).toBe(2);
  });
});
