import { render, screen, waitFor } from "@testing-library/react";
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
  it("renders agents and loads session messages", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
      expect(mockListTools).toHaveBeenCalled();
    });

    expect(screen.getAllByText("予定アシスタント")[0]).toBeInTheDocument();
    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();
  });

  it("applies the Schedule Assistant template in creation form", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getAllByText("予定アシスタント")[0]).toBeInTheDocument();
    });

    await user.click(screen.getByText("＋ 新規作成"));

    expect(screen.getByText("新規エージェント作成")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "予定アシスタントテンプレートを適用",
      })
    );

    const nameInput = screen.getByPlaceholderText("例: 予定アシスタント");
    expect(nameInput).toHaveValue("予定アシスタント");
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

    const input = screen.getByPlaceholderText("メッセージを入力…");
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

    const input = screen.getByPlaceholderText("メッセージを入力…");
    await user.type(input, "テストメッセージ");
    await user.click(screen.getByRole("button", { name: "送信" }));

    expect(
      await screen.findByText("ストリーミングエラーが発生しました。")
    ).toBeInTheDocument();

    // Type new text to verify input is not disabled by streaming
    await user.type(input, "再試行");
    expect(screen.getByRole("button", { name: "送信" })).not.toBeDisabled();
  });
});
