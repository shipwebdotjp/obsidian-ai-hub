import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import AgentsPage from "../AgentsPage";
import { writeAgentSendQueue, createQueuedMessage } from "../agentSendQueue";
import type { AgentRun, AgentRunStatus } from "../../../api/types";

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
  getHitlRun: vi.fn(),
  submitHitlAnswer: vi.fn(),
  cancelHitlRun: vi.fn(),
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
  subscribeAgentRunEvents,
  getHitlRun,
  cancelHitlRun,
} from "../../../api/client";

const mockListAgents = vi.mocked(listAgents);
const mockListTools = vi.mocked(listAgentTools);
const mockListSessions = vi.mocked(listAgentSessions);
const mockGetDetail = vi.mocked(getAgentSessionDetail);
const mockListTemplates = vi.mocked(listPromptTemplates);
const mockStart = vi.mocked(startAgentRun);
const mockSubscribe = vi.mocked(subscribeAgentRunEvents);
const mockGetHitl = vi.mocked(getHitlRun);
const mockCancelHitl = vi.mocked(cancelHitlRun);

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

function run(runId: string, status: AgentRunStatus = "queued"): AgentRun {
  return {
    run_id: runId,
    session_id: session.session_id,
    user_message_id: `u_${runId}`,
    assistant_message_id: null,
    status,
    hitl_run_id: null,
    used_tools: [],
    created_hitl_run_ids: [],
    error_message: null,
    started_at: "",
    finished_at: null,
  };
}

function doneEnvelope(runId: string) {
  return {
    eventId: 1,
    data: {
      type: "done",
      message: {
        message_id: `m_${runId}`,
        session_id: session.session_id,
        sequence: 2,
        role: "assistant",
        content: "ok",
        created_at: new Date().toISOString(),
      },
      run: run(runId, "succeeded"),
      hitl_run_ids: [],
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  mockListAgents.mockResolvedValue({ agents: [agent] });
  mockListTools.mockResolvedValue({ tools: [] });
  mockListSessions.mockResolvedValue({ sessions: [session] });
  vi.mocked(searchAgentMessages).mockResolvedValue({ results: [] });
  mockListTemplates.mockResolvedValue({ templates: [] });
  mockGetDetail.mockResolvedValue({ session, agent, messages: [], runs: [] });
  mockCancelHitl.mockResolvedValue({ success: true });
  mockSubscribe.mockImplementation(async () => {});
});

describe("AgentsPage send queue", () => {
  it("queues messages while streaming and sends them in order after the turn ends", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_rid, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart
      .mockResolvedValueOnce({ run: run("arun_1") })
      .mockResolvedValueOnce({ run: run("arun_2") });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "second");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await screen.findByTestId("agent-queued-messages");
    expect(screen.getByText("待機 1件")).toBeInTheDocument();
    expect(mockStart).toHaveBeenCalledTimes(1);

    emitters[0](doneEnvelope("arun_1"));

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(2));
    expect(mockStart.mock.calls[1][1]).toMatchObject({ content: "second" });
    await waitFor(() =>
      expect(screen.queryByTestId("agent-queued-messages")).not.toBeInTheDocument(),
    );
  });

  it("keeps an in-progress composer draft when the previous turn completes", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_rid, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart.mockResolvedValueOnce({ run: run("arun_1") });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "draft in progress");
    emitters[0](doneEnvelope("arun_1"));

    await waitFor(() => expect(input).toHaveValue("draft in progress"));
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("removes a queued message without sending it", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_rid, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart.mockResolvedValueOnce({ run: run("arun_1") });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "drop me");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await screen.findByTestId("agent-queued-messages");
    await user.click(screen.getByRole("button", { name: "送信待ちメッセージを削除" }));
    await waitFor(() =>
      expect(screen.queryByTestId("agent-queued-messages")).not.toBeInTheDocument(),
    );

    emitters[0](doneEnvelope("arun_1"));
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("restores a persisted queue on load and sends when the session is idle", async () => {
    writeAgentSendQueue(session.session_id, [
      createQueuedMessage({ content: "restored message" }),
    ]);
    mockStart.mockResolvedValueOnce({ run: run("arun_restored") });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    expect(mockStart.mock.calls[0][1]).toMatchObject({ content: "restored message" });
  });

  it("keeps the queued item pending on 409 instead of erroring or looping", async () => {
    writeAgentSendQueue(session.session_id, [
      createQueuedMessage({ content: "blocked message" }),
    ]);
    let activeRunVisible = false;
    mockGetDetail.mockImplementation(async () => ({
      session,
      agent,
      messages: [],
      runs: activeRunVisible ? [run("arun_other", "running")] : [],
    }));
    mockStart.mockImplementation(async () => {
      activeRunVisible = true;
      throw Object.assign(new Error("active run"), { status: 409 });
    });
    mockSubscribe.mockImplementation(async () => {
      await new Promise<void>(() => {});
    });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(screen.getByText("blocked message")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-queued-error")).not.toBeInTheDocument();
  });

  it("holds the queue while a question is pending and sends after it is resolved", async () => {
    const waitingRun = {
      ...run("arun_waiting", "waiting_user"),
      hitl_run_id: "hitl_1",
    };
    mockGetDetail
      .mockResolvedValueOnce({
        session,
        agent,
        messages: [],
        runs: [waitingRun],
        active_run: waitingRun,
      })
      .mockResolvedValue({ session, agent, messages: [], runs: [] });
    mockGetHitl.mockResolvedValue({
      status: "pending_user",
      questions: [
        {
          question_key: "q1",
          question_id: "q1",
          prompt: "Continue?",
          status: "pending",
          choices: [{ value: "yes", label: "Yes" }],
        },
      ],
    } as never);
    writeAgentSendQueue(session.session_id, [
      createQueuedMessage({ content: "after answer" }),
    ]);
    mockStart.mockResolvedValueOnce({ run: run("arun_after") });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>,
    );

    await screen.findByText("Continue?");
    expect(mockStart).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    expect(mockStart.mock.calls[0][1]).toMatchObject({ content: "after answer" });
  });
});
