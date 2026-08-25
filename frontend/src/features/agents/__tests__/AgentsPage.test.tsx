import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import AgentsPage from "../AgentsPage";

vi.mock("../../../api/client", () => ({
  listAgents: vi.fn(),
  listAgentTools: vi.fn(),
  createAgent: vi.fn(),
  updateAgent: vi.fn(),
  deleteAgent: vi.fn(),
  listAgentSessions: vi.fn(),
  createAgentSession: vi.fn(),
  getAgentSessionDetail: vi.fn(),
  deleteAgentSession: vi.fn(),
  streamAgentMessage: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import {
  listAgents,
  listAgentTools,
  createAgent,
  updateAgent,
  deleteAgent,
  listAgentSessions,
  createAgentSession,
  getAgentSessionDetail,
  deleteAgentSession,
  streamAgentMessage,
} from "../../../api/client";

const mockListAgents = vi.mocked(listAgents);
const mockListTools = vi.mocked(listAgentTools);
const mockCreateAgent = vi.mocked(createAgent);
const mockListSessions = vi.mocked(listAgentSessions);
const mockGetSessionDetail = vi.mocked(getAgentSessionDetail);
const mockStreamMessage = vi.mocked(streamAgentMessage);

const sampleAgent = {
  agent_id: "agent_123",
  name: "予定アシスタント",
  system_prompt: "予定を整理するアシスタント",
  provider: null,
  model: null,
  tool_ids: ["calendar_read", "calendar_create_proposal"],
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

const sampleTools = [
  {
    tool_id: "calendar_read",
    name: "カレンダー読取",
    description: "カレンダー予定を取得します",
  },
  {
    tool_id: "calendar_create_proposal",
    name: "カレンダー作成提案 (HITL)",
    description: "カレンダー登録を提案します",
  },
];

const sampleSession = {
  session_id: "asess_456",
  agent_id: "agent_123",
  title: "明日の予定",
  created_at: "2026-08-20T00:00:00Z",
  updated_at: "2026-08-20T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  mockListAgents.mockResolvedValue({ agents: [sampleAgent] });
  mockListTools.mockResolvedValue({ tools: sampleTools });
  mockListSessions.mockResolvedValue({ sessions: [sampleSession] });
  mockGetSessionDetail.mockResolvedValue({
    session: sampleSession,
    agent: sampleAgent,
    messages: [
      {
        message_id: "msg_1",
        session_id: "asess_456",
        sequence: 1,
        role: "user",
        content: "こんにちは",
        created_at: "2026-08-20T00:00:00Z",
      },
      {
        message_id: "msg_2",
        session_id: "asess_456",
        sequence: 2,
        role: "assistant",
        content: "こんにちは！何かお手伝いできますか？",
        created_at: "2026-08-20T00:00:01Z",
      },
    ],
    runs: [],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AgentsPage", () => {
  it("renders split layout with upper agents section and lower conversation history section", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
      expect(mockListTools).toHaveBeenCalled();
    });

    expect(screen.getByText("AIエージェント")).toBeInTheDocument();
    expect(screen.getByText("会話履歴")).toBeInTheDocument();
    expect(screen.getAllByText("予定アシスタント")[0]).toBeInTheDocument();
    expect(await screen.findByText("明日の予定")).toBeInTheDocument();
    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();
  });

  it("displays empty conversation history message when agent has no sessions", async () => {
    mockListSessions.mockResolvedValue({ sessions: [] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    expect(screen.getByText("会話履歴がありません")).toBeInTheDocument();
  });

  it("displays unselected message when no agent is selected", async () => {
    mockListAgents.mockResolvedValue({ agents: [] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    expect(screen.getByText("エージェントを選択してください")).toBeInTheDocument();
  });

  it("sends message and handles streaming and HITL proposal link", async () => {
    const user = userEvent.setup();

    mockStreamMessage.mockImplementation(
      async (sessionId, content, onEvent) => {
        onEvent({ type: "text", delta: "カレンダーへの登録申請を作成" });
        onEvent({
          type: "done",
          message: {
            message_id: "msg_3",
            session_id: sessionId,
            sequence: 3,
            role: "assistant",
            content: "カレンダーへの登録申請を作成しました。",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_1",
            session_id: sessionId,
            user_message_id: "msg_2",
            assistant_message_id: "msg_3",
            status: "succeeded",
            used_tools: [],
            created_hitl_run_ids: ["hrun_inbox_calendar_999"],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: ["hrun_inbox_calendar_999"],
        });
      }
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "明日10時にミーティングを入れて");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "asess_456",
        "明日10時にミーティングを入れて",
        expect.any(Function),
        expect.any(Object)
      );
    });

    expect(
      await screen.findByText("承認待ちの登録申請が作成されました")
    ).toBeInTheDocument();
    expect(screen.getByText("→ 確認待ち画面へ移動する")).toBeInTheDocument();
  });

  it("displays error message when streaming receives an error event", async () => {
    const user = userEvent.setup();

    mockStreamMessage.mockImplementation(
      async (sessionId, content, onEvent) => {
        onEvent({
          type: "error",
          error: "ストリーミングエラーが発生しました。",
        });
      }
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "テストメッセージ");
    await user.click(screen.getByRole("button", { name: "送信" }));

    expect(
      await screen.findByText("ストリーミングエラーが発生しました。")
    ).toBeInTheDocument();

    // Type new text to verify input is not disabled by streaming
    await user.type(input, "再試行");
    expect(screen.getByRole("button", { name: "送信" })).not.toBeDisabled();
  });

  it("opens the session referenced by ?session_id=... on deep link", async () => {
    const otherAgent = {
      ...sampleAgent,
      agent_id: "agent_999",
      name: "別エージェント",
    };
    const otherSession = {
      ...sampleSession,
      session_id: "asess_777",
      agent_id: "agent_999",
      title: "ディープリンク先",
    };

    mockListAgents.mockResolvedValue({ agents: [sampleAgent, otherAgent] });
    mockListSessions.mockImplementation(async (agentId: string) => {
      if (agentId === "agent_999") {
        return { sessions: [otherSession] };
      }
      return { sessions: [sampleSession] };
    });
    mockGetSessionDetail.mockResolvedValue({
      session: otherSession,
      agent: otherAgent,
      messages: [
        {
          message_id: "msg_dl_1",
          session_id: "asess_777",
          sequence: 1,
          role: "user",
          content: "ディープリンク経由で開きました",
          created_at: "2026-08-20T00:00:00Z",
        },
        {
          message_id: "msg_dl_2",
          session_id: "asess_777",
          sequence: 2,
          role: "assistant",
          content: "ディープリンク応答",
          created_at: "2026-08-20T00:00:01Z",
        },
      ],
      runs: [],
    });

    render(
      <MemoryRouter initialEntries={["/agents?session_id=asess_777"]}>
        <AgentsPage />
      </MemoryRouter>
    );

    // The deep-link target agent should be resolved, not the first agent
    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalledWith("asess_777");
    });
    expect(
      await screen.findByText("ディープリンク応答")
    ).toBeInTheDocument();
    // The other agent's session should appear in the session bar
    expect(screen.getByText("ディープリンク先")).toBeInTheDocument();
  });

  it("falls back to first agent when the deep-link session does not exist", async () => {
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => {
      if (sessionId === "asess_missing") {
        throw Object.assign(new Error("not found"), { status: 404 });
      }
      return {
        session: sampleSession,
        agent: sampleAgent,
        messages: [
          {
            message_id: "msg_1",
            session_id: "asess_456",
            sequence: 1,
            role: "user",
            content: "こんにちは",
            created_at: "2026-08-20T00:00:00Z",
          },
          {
            message_id: "msg_2",
            session_id: "asess_456",
            sequence: 2,
            role: "assistant",
            content: "こんにちは！何かお手伝いできますか？",
            created_at: "2026-08-20T00:00:01Z",
          },
        ],
        runs: [],
      };
    });

    render(
      <MemoryRouter initialEntries={["/agents?session_id=asess_missing"]}>
        <AgentsPage />
      </MemoryRouter>
    );

    // Falls back to first agent, normal load should complete
    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalledWith("asess_missing");
    });
    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();
  });

  it("batches token rendering per frame and keeps tool preparation and stale frames safe", async () => {
    const user = userEvent.setup();
    const callbacks = new Map<number, FrameRequestCallback>();
    let nextFrameId = 1;
    const originalRequestAnimationFrame = window.requestAnimationFrame;
    const originalCancelAnimationFrame = window.cancelAnimationFrame;
    const requestAnimationFrame = vi.fn((callback: FrameRequestCallback) => {
      const frameId = nextFrameId;
      nextFrameId += 1;
      callbacks.set(frameId, callback);
      return frameId;
    });
    const cancelAnimationFrame = vi.fn((frameId: number) => {
      callbacks.delete(frameId);
    });
    Object.defineProperty(window, "requestAnimationFrame", {
      configurable: true,
      value: requestAnimationFrame,
    });
    Object.defineProperty(window, "cancelAnimationFrame", {
      configurable: true,
      value: cancelAnimationFrame,
    });

    let emitStreamEvent: ((event: any) => void) | null = null;
    let finishStream!: () => void;
    mockStreamMessage.mockImplementation(
      async (_sessionId, _content, onEvent) => {
        emitStreamEvent = onEvent;
        await new Promise<void>((resolve) => {
          finishStream = resolve;
        });
      }
    );

    try {
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = await screen.findByPlaceholderText(/^メッセージを入力/);
      await user.type(input, "ストリーミングを試す");
      await user.click(screen.getByRole("button", { name: "送信" }));
      await waitFor(() => expect(emitStreamEvent).not.toBeNull());
      const emit = emitStreamEvent!;

      act(() => {
        emit({
          type: "tool_call_detected",
          call_key: "1:0",
          tool_name: "vault_search",
          iteration: 1,
        });
      });
      expect(screen.getAllByText("準備中…").length).toBeGreaterThan(0);
      expect(screen.queryByText("引数")).not.toBeInTheDocument();

      act(() => {
        emit({
          type: "tool_call_start",
          call_id: "call_1",
          call_key: "1:0",
          tool_name: "vault_search",
          args: { query: "予定" },
          iteration: 1,
        });
      });
      expect(screen.getAllByText("実行中…").length).toBeGreaterThan(0);

      act(() => {
        emit({
          type: "tool_call_end",
          call_id: "call_1",
          call_key: "1:0",
          tool_name: "vault_search",
          status: "succeeded",
          result: "検索結果",
          hitl_run_id: null,
          error: null,
          iteration: 1,
        });
      });
      expect(screen.getByText("成功")).toBeInTheDocument();

      act(() => {
        emit({ type: "text", delta: "token-one " });
        emit({ type: "text", delta: "token-two" });
      });
      expect(requestAnimationFrame).toHaveBeenCalledTimes(1);
      expect(screen.queryByText("token-one token-two")).not.toBeInTheDocument();

      act(() => {
        const queuedCallbacks = [...callbacks.values()];
        callbacks.clear();
        queuedCallbacks.forEach((callback) => callback(0));
      });
      expect(await screen.findByText("token-one token-two")).toBeInTheDocument();

      act(() => emit({ type: "text", delta: "stale-token" }));
      const staleFrame = [...callbacks.values()][0];
      expect(staleFrame).toBeDefined();

      act(() => {
        emit({
          type: "done",
          message: {
            message_id: "msg_stream_done",
            session_id: sampleSession.session_id,
            sequence: 4,
            role: "assistant",
            content: "確定済み本文",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_stream_done",
            session_id: sampleSession.session_id,
            user_message_id: "msg_stream_user",
            assistant_message_id: "msg_stream_done",
            status: "succeeded",
            used_tools: ["vault_search"],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
        });
      });
      expect(cancelAnimationFrame).toHaveBeenCalled();
      act(() => staleFrame!(0));
      expect(screen.queryByText("stale-token")).not.toBeInTheDocument();

      finishStream();
    } finally {
      Object.defineProperty(window, "requestAnimationFrame", {
        configurable: true,
        value: originalRequestAnimationFrame,
      });
      Object.defineProperty(window, "cancelAnimationFrame", {
        configurable: true,
        value: originalCancelAnimationFrame,
      });
    }
  });
});
