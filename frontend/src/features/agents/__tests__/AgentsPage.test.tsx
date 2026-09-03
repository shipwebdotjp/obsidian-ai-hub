import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  searchAgentMessages: vi.fn(),
  createAgentSession: vi.fn(),
  getAgentSessionDetail: vi.fn(),
  deleteAgentSession: vi.fn(),
  listPromptTemplates: vi.fn(),
  createPromptTemplate: vi.fn(),
  updatePromptTemplate: vi.fn(),
  deletePromptTemplate: vi.fn(),
  updateAgentSession: vi.fn(),
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
  searchAgentMessages,
  createAgentSession,
  getAgentSessionDetail,
  deleteAgentSession,
  listPromptTemplates,
  updateAgentSession,
  streamAgentMessage,
} from "../../../api/client";

const mockListAgents = vi.mocked(listAgents);
const mockListTools = vi.mocked(listAgentTools);
const mockCreateAgent = vi.mocked(createAgent);
const mockListSessions = vi.mocked(listAgentSessions);
const mockSearchMessages = vi.mocked(searchAgentMessages);
const mockGetSessionDetail = vi.mocked(getAgentSessionDetail);
const mockListTemplates = vi.mocked(listPromptTemplates);
const mockUpdateAgent = vi.mocked(updateAgent);
const mockUpdateSession = vi.mocked(updateAgentSession);
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
  localStorage.clear();
  sessionStorage.clear();
  mockListAgents.mockResolvedValue({ agents: [sampleAgent] });
  mockListTools.mockResolvedValue({ tools: sampleTools });
  mockListSessions.mockResolvedValue({ sessions: [sampleSession] });
  mockSearchMessages.mockResolvedValue({ results: [] });
  mockListTemplates.mockResolvedValue({ templates: [] });
  mockUpdateAgent.mockResolvedValue({ agent: sampleAgent });
  mockUpdateSession.mockResolvedValue({ session: sampleSession });
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

  it("searches messages across agents and opens the exact matching message", async () => {
    const user = userEvent.setup();
    const otherAgent = {
      ...sampleAgent,
      agent_id: "agent_999",
      name: "リサーチアシスタント",
    };
    const otherSession = {
      ...sampleSession,
      session_id: "asess_999",
      agent_id: otherAgent.agent_id,
      title: "横断検索の会話",
    };
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });

    mockListAgents.mockResolvedValue({ agents: [sampleAgent, otherAgent] });
    mockListSessions.mockImplementation(async (agentId) => ({
      sessions: agentId === otherAgent.agent_id ? [otherSession] : [sampleSession],
    }));
    mockSearchMessages.mockResolvedValue({
      results: [
        {
          agent_id: otherAgent.agent_id,
          agent_name: otherAgent.name,
          session_id: otherSession.session_id,
          session_title: otherSession.title,
          session_updated_at: otherSession.updated_at,
          message_id: "msg_other_hit",
          role: "assistant",
          snippet: "横断検索で見つかった回答です",
          created_at: otherSession.updated_at,
        },
      ],
    });
    mockGetSessionDetail.mockImplementation(async (sessionId) => {
      if (sessionId === otherSession.session_id) {
        return {
          session: otherSession,
          agent: otherAgent,
          messages: [
            {
              message_id: "msg_other_hit",
              session_id: otherSession.session_id,
              sequence: 1,
              role: "assistant",
              content: "横断検索で見つかった回答です",
              created_at: otherSession.updated_at,
            },
          ],
          runs: [],
        };
      }
      return {
        session: sampleSession,
        agent: sampleAgent,
        messages: [],
        runs: [],
      };
    });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await user.type(await screen.findByRole("searchbox", { name: "会話履歴を検索" }), "横断検索");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 220)));

    expect(mockSearchMessages).toHaveBeenCalledWith("横断検索");
    const result = await screen.findByTestId("agent-message-search-result-msg_other_hit");
    expect(within(result).getByText("リサーチアシスタント")).toBeInTheDocument();
    await user.click(result);

    await waitFor(() => {
      expect(document.querySelector('[data-message-id="msg_other_hit"]')).toBeInTheDocument();
      expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
    });
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
        expect.any(Object),
        undefined
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

  it("attaches an image file, shows preview, and passes attachments to streamAgentMessage", async () => {
    const user = userEvent.setup();

    mockStreamMessage.mockImplementation(
      async (sessionId, content, onEvent, _signal, attachments) => {
        expect(content).toBe("この画像を見て");
        expect(attachments).toEqual([
          { name: "pixel.png", mime_type: "image/png", data: "QUJD" },
        ]);
        onEvent({
          type: "done",
          message: {
            message_id: "msg_img_done",
            session_id: sessionId,
            sequence: 4,
            role: "assistant",
            content: "画像を見ました",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_img_done",
            session_id: sessionId,
            user_message_id: "msg_img_user",
            assistant_message_id: "msg_img_done",
            status: "succeeded",
            used_tools: [],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
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

    const file = new File([new Uint8Array([0x41, 0x42, 0x43])], "pixel.png", {
      type: "image/png",
    });
    const fileInput = screen.getByTestId(
      "agent-image-input"
    ) as HTMLInputElement;

    await user.upload(fileInput, file);

    expect(await screen.findByAltText("pixel.png")).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "この画像を見て");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "asess_456",
        "この画像を見て",
        expect.any(Function),
        expect.any(Object),
        [
          { name: "pixel.png", mime_type: "image/png", data: "QUJD" },
        ]
      );
    });

    // After send, the preview row clears (image no longer rendered above the form).
    expect(screen.queryByAltText("pixel.png")).not.toBeInTheDocument();
  });

  it("allows sending with only an attachment and no text", async () => {
    const user = userEvent.setup();
    mockStreamMessage.mockImplementation(
      async (sessionId, content, _onEvent, _signal, attachments) => {
        expect(content).toBe("");
        expect(attachments).toEqual([
          { name: "pixel.png", mime_type: "image/png", data: "QUJD" },
        ]);
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

    const file = new File([new Uint8Array([0x41, 0x42, 0x43])], "pixel.png", {
      type: "image/png",
    });
    const fileInput = screen.getByTestId(
      "agent-image-input"
    ) as HTMLInputElement;
    await user.upload(fileInput, file);

    expect(await screen.findByAltText("pixel.png")).toBeInTheDocument();

    // Submit without typing any text — the send button is enabled by the image.
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "asess_456",
        "",
        expect.any(Function),
        expect.any(Object),
        [{ name: "pixel.png", mime_type: "image/png", data: "QUJD" }]
      );
    });
  });

  it("rejects non-image file selections and shows an error", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "doc.pdf", {
      type: "application/pdf",
    });
    const fileInput = screen.getByTestId(
      "agent-image-input"
    ) as HTMLInputElement;
    // userEvent.upload respects the input's `accept` filter and would drop the
    // PDF silently. Use fireEvent.change directly so we exercise the manual
    // file validation guard.
    Object.defineProperty(fileInput, "files", {
      configurable: true,
      value: [file],
    });
    fireEvent.change(fileInput);

    expect(
      await screen.findByText(
        /画像ファイル以外は添付できません: doc\.pdf/
      )
    ).toBeInTheDocument();
  });

  it("attaches a dropped file, shows preview, and passes attachments to streamAgentMessage", async () => {
    const user = userEvent.setup();

    mockStreamMessage.mockImplementation(
      async (sessionId, content, _onEvent, _signal, attachments) => {
        expect(content).toBe("drop して確認");
        expect(attachments).toEqual([
          { name: "dropped.png", mime_type: "image/png", data: "UkZT" },
        ]);
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

    const file = new File([new Uint8Array([0x52, 0x46, 0x53])], "dropped.png", {
      type: "image/png",
    });
    const form = screen.getByPlaceholderText(/^メッセージを入力/).closest("form");
    expect(form).not.toBeNull();

    fireEvent.dragOver(form!, { dataTransfer: { types: ["Files"] } });
    expect(
      screen.getByTestId("agent-drop-overlay")
    ).toBeInTheDocument();

    fireEvent.drop(form!, {
      dataTransfer: { files: [file], types: ["Files"] },
    });

    expect(await screen.findByAltText("dropped.png")).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "drop して確認");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "asess_456",
        "drop して確認",
        expect.any(Function),
        expect.any(Object),
        [{ name: "dropped.png", mime_type: "image/png", data: "UkZT" }]
      );
    });
  });

  it("rejects a non-image file dropped on the form", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );
    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const file = new File([new Uint8Array([0x25, 0x50, 0x44, 0x46])], "doc.pdf", {
      type: "application/pdf",
    });
    const form = screen.getByPlaceholderText(/^メッセージを入力/).closest("form");
    expect(form).not.toBeNull();

    fireEvent.dragOver(form!, { dataTransfer: { types: ["Files"] } });
    fireEvent.drop(form!, {
      dataTransfer: { files: [file], types: ["Files"] },
    });

    expect(
      await screen.findByText(
        /画像ファイル以外は添付できません: doc\.pdf/
      )
    ).toBeInTheDocument();
  });

  it("attaches an image pasted from the clipboard into the textarea", async () => {
    const user = userEvent.setup();

    mockStreamMessage.mockImplementation(
      async (sessionId, content, _onEvent, _signal, attachments) => {
        expect(content).toBe("これは？");
        expect(attachments).toEqual([
          { name: "image.png", mime_type: "image/png", data: "UEFT" },
        ]);
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

    const pastedFile = new File([new Uint8Array([0x50, 0x41, 0x53])], "image.png", {
      type: "image/png",
    });
    const fakeItem = {
      kind: "file",
      type: "image/png",
      getAsFile: vi.fn(() => pastedFile),
    };
    const items = [fakeItem];
    const clipboardData = {
      items,
      files: [],
      getData: vi.fn(),
      setData: vi.fn(),
    };

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    fireEvent.paste(input, { clipboardData });

    expect(
      await screen.findByAltText("image.png")
    ).toBeInTheDocument();

    await user.type(input, "これは？");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith(
        "asess_456",
        "これは？",
        expect.any(Function),
        expect.any(Object),
        [{ name: "image.png", mime_type: "image/png", data: "UEFT" }]
      );
    });
  });

  it("opens the mobile sidebar drawer from the chat header", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const openButton = screen.getByRole("button", { name: "エージェントと会話を選択" });
    await user.click(openButton);

    // The mobile drawer renders the sidebar content.
    const closeButton = screen.getByRole("button", { name: "サイドバーを閉じる" });
    const drawer = closeButton.closest("div[class*=\"fixed\"]");
    expect(drawer).not.toBeNull();
    expect(within(drawer as HTMLElement).getByText("AIエージェント")).toBeInTheDocument();
    expect(within(drawer as HTMLElement).getByText("会話履歴")).toBeInTheDocument();
  });

  it("closes the mobile sidebar drawer when the close button is pressed", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "エージェントと会話を選択" }));
    expect(screen.getByRole("button", { name: "サイドバーを閉じる" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "サイドバーを閉じる" }));
    expect(screen.queryByRole("button", { name: "サイドバーを閉じる" })).not.toBeInTheDocument();
  });

  it("collapses and expands the desktop left pane", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    expect(screen.getByText("AIエージェント")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "サイドバーを畳む" }));
    expect(screen.queryByText("AIエージェント")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "サイドバーを展開" }));
    expect(screen.getByText("AIエージェント")).toBeInTheDocument();
  });

  it("shows a mobile open button on the empty state when no agent exists", async () => {
    mockListAgents.mockResolvedValue({ agents: [] });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    const openButton = screen.getByRole("button", { name: "エージェントを選択" });
    await user.click(openButton);
    expect(screen.getByRole("button", { name: "サイドバーを閉じる" })).toBeInTheDocument();
  });

  it("shows a desktop expand button on the empty state when the sidebar is collapsed", async () => {
    mockListAgents.mockResolvedValue({ agents: [] });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    // Collapse the sidebar first.
    await user.click(screen.getByRole("button", { name: "サイドバーを畳む" }));
    expect(screen.queryByText("AIエージェント")).not.toBeInTheDocument();

    // The empty state offers a desktop-visible expand control.
    const expandButton = screen.getByRole("button", { name: "サイドバーを展開" });
    await user.click(expandButton);
    expect(screen.getByText("AIエージェント")).toBeInTheDocument();
  });

  it("ignores text-only clipboard pastes", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );
    expect(
      await screen.findByText("こんにちは！何かお手伝いできますか？")
    ).toBeInTheDocument();

    const items = [
      { kind: "string", type: "text/plain", getAsFile: () => null },
    ];
    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    fireEvent.paste(input, {
      clipboardData: { items, files: [], getData: () => "hello" },
    });

    // No preview rendered for non-image pastes.
    expect(screen.queryByTestId("agent-drop-overlay")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/画像ファイル以外/)
    ).not.toBeInTheDocument();
    // send button stays disabled because nothing was attached.
    expect(screen.getByRole("button", { name: "送信" })).toBeDisabled();
  });

  it("auto-saves input text as a draft after a debounce", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "下書き保存テスト");

    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBeNull();
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));

    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBe(
      "下書き保存テスト",
    );
  });

  it("loads a saved draft when the session is selected", async () => {
    sessionStorage.setItem("oaih:prompt-draft:agents:asess_456", "復元される下書き");

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    const input = screen.getByPlaceholderText(/^メッセージを入力/) as HTMLTextAreaElement;
    await waitFor(() => {
      expect(input.value).toBe("復元される下書き");
    });
  });

  it("clears the draft after a message is sent successfully", async () => {
    const user = userEvent.setup();
    mockStreamMessage.mockImplementation(
      async (sessionId, content, onEvent) => {
        onEvent({ type: "text", delta: "送信完了" });
        onEvent({
          type: "done",
          message: {
            message_id: "msg_clear_draft",
            session_id: sessionId,
            sequence: 3,
            role: "assistant",
            content: "送信完了",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_clear_draft",
            session_id: sessionId,
            user_message_id: "msg_clear_draft_user",
            assistant_message_id: "msg_clear_draft",
            status: "succeeded",
            used_tools: [],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
        });
      }
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    const input = await screen.findByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "クリアされる下書き");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => {
      expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBeNull();
    });
  });

  it("keeps the pre-send text as the session draft when send fails", async () => {
    const user = userEvent.setup();
    mockStreamMessage.mockRejectedValue(new Error("送信失敗"));

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    const input = (await screen.findByPlaceholderText(
      /^メッセージを入力/,
    )) as HTMLTextAreaElement;
    await user.type(input, "失敗しても残る下書き");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));

    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => {
      expect(input.value).toBe("失敗しても残る下書き");
      expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBe(
        "失敗しても残る下書き",
      );
    });
  });

  it("does not touch session B when A's stream ends after switching", async () => {
    const user = userEvent.setup();
    const secondSession = { ...sampleSession, session_id: "asess_789", title: "別の会話" };
    mockListSessions.mockResolvedValue({ sessions: [sampleSession, secondSession] });
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : sampleSession,
      agent: sampleAgent,
      messages: [],
      runs: [],
    }));
    let capturedOnEvent: ((event: never) => void) | null = null;
    mockStreamMessage.mockImplementation(
      (_sessionId: string, _content: string, onEvent: (event: never) => void) => {
        capturedOnEvent = onEvent;
        return new Promise(() => {}) as unknown as Promise<void>;
      },
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    const input = (await screen.findByPlaceholderText(
      /^メッセージを入力/,
    )) as HTMLTextAreaElement;
    await user.type(input, "Aの送信文");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));

    await user.click(screen.getByRole("button", { name: "送信" }));
    // Switch to B while A's stream is still running (this aborts A's stream).
    await user.click(screen.getByText("別の会話"));
    await waitFor(() => {
      expect(input.value).toBe("");
    });

    await user.type(input, "Bの入力中");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_789")).toBe("Bの入力中");

    // A's stale stream event must not affect B; A's draft stays (never deleted).
    await act(async () => {
      capturedOnEvent?.({
        type: "done",
        message: {
          message_id: "msg_stale",
          session_id: "asess_456",
          sequence: 3,
          role: "assistant",
          content: "stale",
          created_at: new Date().toISOString(),
        },
        run: {
          run_id: "arun_stale",
          session_id: "asess_456",
          user_message_id: "msg_stale_user",
          assistant_message_id: "msg_stale",
          status: "succeeded",
          used_tools: [],
          created_hitl_run_ids: [],
          error_message: null,
          started_at: "",
          finished_at: "",
        },
        hitl_run_ids: [],
      } as never);
    });

    expect(input.value).toBe("Bの入力中");
    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_789")).toBe("Bの入力中");
    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBe("Aの送信文");
  });

  it("keeps per-session drafts separated when switching sessions", async () => {
    const user = userEvent.setup();
    const secondSession = { ...sampleSession, session_id: "asess_789", title: "別の会話" };
    mockListSessions.mockResolvedValue({ sessions: [sampleSession, secondSession] });
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : sampleSession,
      agent: sampleAgent,
      messages: [],
      runs: [],
    }));

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    const input = (await screen.findByPlaceholderText(
      /^メッセージを入力/,
    )) as HTMLTextAreaElement;
    await user.type(input, "Aの下書き");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:agents:asess_456")).toBe("Aの下書き");

    // Switch to B: A's content must not leak into B, and B starts empty.
    await user.click(screen.getByText("別の会話"));
    await waitFor(() => {
      expect(input.value).toBe("");
    });

    await user.type(input, "Bの下書き");
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));

    // Switch back to A: A's draft is restored.
    await user.click(screen.getByText("明日の予定"));
    await waitFor(() => {
      expect(input.value).toBe("Aの下書き");
    });

    // And back to B: B's draft is restored.
    await user.click(screen.getByText("別の会話"));
    await waitFor(() => {
      expect(input.value).toBe("Bの下書き");
    });
  });

  it("saves attached images per session and restores them without mixing", async () => {
    const user = userEvent.setup();
    const secondSession = { ...sampleSession, session_id: "asess_789", title: "別の会話" };
    mockListSessions.mockResolvedValue({ sessions: [sampleSession, secondSession] });
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : sampleSession,
      agent: sampleAgent,
      messages: [],
      runs: [],
    }));

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await screen.findByPlaceholderText(/^メッセージを入力/);
    const file = new File([new Uint8Array([0x41, 0x42, 0x43])], "a-image.png", {
      type: "image/png",
    });
    const fileInput = screen.getByTestId("agent-image-input") as HTMLInputElement;
    await user.upload(fileInput, file);
    expect(await screen.findByAltText("a-image.png")).toBeInTheDocument();

    await act(() => new Promise((resolve) => window.setTimeout(resolve, 650)));
    const savedA = JSON.parse(window.localStorage.getItem("agent-draft:asess_456") || "{}");
    expect(savedA.attachments).toEqual([
      { name: "a-image.png", mime_type: "image/png", data: "QUJD", size: 3 },
    ]);

    // Switch to B: A's image must not leak into B.
    await user.click(screen.getByText("別の会話"));
    await waitFor(() => {
      expect(screen.queryByAltText("a-image.png")).not.toBeInTheDocument();
    });
    expect(window.localStorage.getItem("agent-draft:asess_789")).toBeNull();

    // Switch back to A: A's image draft is restored.
    await user.click(screen.getByText("明日の予定"));
    expect(await screen.findByAltText("a-image.png")).toBeInTheDocument();
  });

  function seedImageDraft(sessionId: string, name = "seed.png") {
    window.localStorage.setItem(
      `agent-draft:${sessionId}`,
      JSON.stringify({
        text: "",
        attachments: [{ name, mime_type: "image/png", data: "QUJD", size: 3 }],
        savedAt: new Date().toISOString(),
      }),
    );
  }

  function doneEvent(sessionId: string) {
    return {
      type: "done",
      message: {
        message_id: `msg_done_${sessionId}`,
        session_id: sessionId,
        sequence: 3,
        role: "assistant",
        content: "送信完了",
        created_at: new Date().toISOString(),
      },
      run: {
        run_id: `arun_done_${sessionId}`,
        session_id: sessionId,
        user_message_id: `msg_done_${sessionId}_user`,
        assistant_message_id: `msg_done_${sessionId}`,
        status: "succeeded",
        used_tools: [],
        created_hitl_run_ids: [],
        error_message: null,
        started_at: "",
        finished_at: "",
      },
      hitl_run_ids: [],
    } as never;
  }

  it("deletes the image draft only after a successful send", async () => {
    const user = userEvent.setup();
    seedImageDraft("asess_456");
    mockStreamMessage.mockImplementation(async (_sessionId, _content, onEvent) => {
      onEvent(doneEvent("asess_456"));
    });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByAltText("seed.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(window.localStorage.getItem("agent-draft:asess_456")).toBeNull();
    });
    expect(screen.queryByAltText("seed.png")).not.toBeInTheDocument();
  });

  it("keeps the image draft when send fails", async () => {
    const user = userEvent.setup();
    seedImageDraft("asess_456");
    mockStreamMessage.mockRejectedValue(new Error("送信失敗"));

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByAltText("seed.png")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(screen.getByText("送信失敗")).toBeInTheDocument();
    });
    const kept = JSON.parse(window.localStorage.getItem("agent-draft:asess_456") || "{}");
    expect(kept.attachments).toEqual([
      { name: "seed.png", mime_type: "image/png", data: "QUJD", size: 3 },
    ]);
    // The draft preview row (not the optimistic message) shows the image again.
    expect(
      within(screen.getByLabelText("送信前の添付画像")).getByAltText("seed.png"),
    ).toBeInTheDocument();
  });

  it("does not touch session B images when A's send ends after switching", async () => {
    const user = userEvent.setup();
    const secondSession = { ...sampleSession, session_id: "asess_789", title: "別の会話" };
    mockListSessions.mockResolvedValue({ sessions: [sampleSession, secondSession] });
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : sampleSession,
      agent: sampleAgent,
      messages: [],
      runs: [],
    }));
    seedImageDraft("asess_456", "a-image.png");
    let capturedOnEvent: ((event: never) => void) | null = null;
    mockStreamMessage.mockImplementation(
      (_sessionId: string, _content: string, onEvent: (event: never) => void) => {
        capturedOnEvent = onEvent;
        return new Promise(() => {}) as unknown as Promise<void>;
      },
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByAltText("a-image.png")).toBeInTheDocument();
    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.click(screen.getByRole("button", { name: "送信" }));

    // Switch to B while A's stream is still running (this aborts A's stream).
    await user.click(screen.getByText("別の会話"));
    await waitFor(() => {
      expect(screen.queryByAltText("a-image.png")).not.toBeInTheDocument();
    });
    expect(input).toHaveValue("");

    // A's stale completion must not affect B; A's image draft stays.
    await act(async () => {
      capturedOnEvent?.(doneEvent("asess_456"));
    });
    expect(screen.queryByAltText("a-image.png")).not.toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(window.localStorage.getItem("agent-draft:asess_789")).toBeNull();
    const keptA = JSON.parse(window.localStorage.getItem("agent-draft:asess_456") || "{}");
    expect(keptA.attachments).toEqual([
      { name: "a-image.png", mime_type: "image/png", data: "QUJD", size: 3 },
    ]);

    // Switch back to A: A's image draft is restored.
    await user.click(screen.getByText("明日の予定"));
    expect(await screen.findByAltText("a-image.png")).toBeInTheDocument();
  });

  it("renders a two-row input footer with plus menu and send icon", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    const plusButton = screen.getByRole("button", { name: "追加メニュー" });
    expect(plusButton).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "送信" })).toBeInTheDocument();
    expect(screen.getByText("既定")).toBeInTheDocument();
  });

  it("opens the plus menu and shows template and image upload options", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "追加メニュー" }));
    expect(screen.getByRole("button", { name: "テンプレート" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "画像アップロード" })).toBeInTheDocument();
  });

  it("opens the template selector from the plus menu", async () => {
    const user = userEvent.setup();
    mockListTemplates.mockResolvedValue({
      templates: [
        {
          template_id: "tpl_1",
          agent_id: "agent_123",
          name: "挨拶",
          content: "こんにちは、何かお手伝いできますか？",
          display_order: 0,
          created_at: "2026-08-20T00:00:00Z",
          updated_at: "2026-08-20T00:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListTemplates).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "追加メニュー" }));
    const templateButton = screen.getByRole("button", { name: "テンプレート" });
    expect(templateButton).not.toBeDisabled();
    await user.click(templateButton);

    await waitFor(() => {
      expect(screen.getByTestId("agent-template-selector")).toBeInTheDocument();
    });
    const selector = screen.getByTestId("agent-template-selector");
    expect(within(selector).getByText(/登録済みテンプレート/)).toBeInTheDocument();
    expect(within(selector).getByText("挨拶")).toBeInTheDocument();
  });

  it("shows a settings gear icon in the agent header", async () => {
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    expect(screen.getByRole("button", { name: "設定編集" })).toBeInTheDocument();
  });

  it("shows a trash icon in the edit form when editing an agent", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "設定編集" }));
    expect(screen.getByRole("button", { name: "エージェントを削除" })).toBeInTheDocument();
  });

  it("toggles agent pin when the pin button is clicked and reloads the agent list", async () => {
    const user = userEvent.setup();
    const pinnedAgent = { ...sampleAgent, pinned_at: "2026-08-25T00:00:00Z" };

    mockUpdateAgent.mockResolvedValue({ agent: pinnedAgent });
    // After pin, listAgents returns the pinned agent
    mockListAgents
      .mockResolvedValueOnce({ agents: [sampleAgent] })
      .mockResolvedValueOnce({ agents: [pinnedAgent] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    const pinButtons = screen.getAllByRole("button", { name: "ピン留めする" });
    const pinButton = pinButtons[0];
    expect(pinButton).toHaveAttribute("aria-pressed", "false");

    await user.click(pinButton);

    await waitFor(() => {
      expect(mockUpdateAgent).toHaveBeenCalledWith("agent_123", { pinned: true });
    });

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalledTimes(2);
    });
  });

  it("toggles session pin via the three-dot menu and reloads the session list", async () => {
    const user = userEvent.setup();
    const pinnedSession = { ...sampleSession, pinned_at: "2026-08-25T00:00:00Z" };

    mockUpdateSession.mockResolvedValue({ session: pinnedSession });
    mockListSessions
      .mockResolvedValueOnce({ sessions: [sampleSession] })
      .mockResolvedValueOnce({ sessions: [pinnedSession] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalled();
    });

    const menuButton = screen.getByRole("button", { name: "操作メニュー" });
    await user.click(menuButton);

    const pinMenuItem = screen.getByRole("button", { name: "会話をピン留めする" });
    await user.click(pinMenuItem);

    await waitFor(() => {
      expect(mockUpdateSession).toHaveBeenCalledWith("asess_456", { pinned: true });
    });

    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalledTimes(2);
    });
  });

  it("edits session title via the three-dot menu and updates the list display", async () => {
    const user = userEvent.setup();
    const updatedSession = { ...sampleSession, title: "更新後の会議タイトル" };

    mockUpdateSession.mockResolvedValue({ session: updatedSession });
    mockListSessions
      .mockResolvedValueOnce({ sessions: [sampleSession] })
      .mockResolvedValueOnce({ sessions: [updatedSession] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalled();
    });

    const menuButton = screen.getByRole("button", { name: "操作メニュー" });
    await user.click(menuButton);

    const editMenuItem = screen.getByRole("button", { name: "会話タイトルを変更" });
    await user.click(editMenuItem);

    const dialog = screen.getByRole("dialog", { name: "会話タイトルの変更" });
    expect(dialog).toBeInTheDocument();

    const titleInput = screen.getByPlaceholderText("会話タイトルを入力");
    await user.clear(titleInput);
    await user.type(titleInput, "更新後の会議タイトル");

    const saveButton = screen.getByRole("button", { name: "保存する" });
    await user.click(saveButton);

    await waitFor(() => {
      expect(mockUpdateSession).toHaveBeenCalledWith("asess_456", {
        title: "更新後の会議タイトル",
      });
    });

    await waitFor(() => {
      expect(screen.getByText("更新後の会議タイトル")).toBeInTheDocument();
    });
  });

  it("opens deletion modal from the three-dot menu and deletes session", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalled();
    });

    const menuButton = screen.getByRole("button", { name: "操作メニュー" });
    await user.click(menuButton);

    const deleteMenuItem = screen.getByRole("button", { name: "会話を削除" });
    await user.click(deleteMenuItem);

    expect(screen.getByText("会話履歴の削除確認")).toBeInTheDocument();
  });

  it("updates session title in the list without page reload when SSE done event returns session_title", async () => {
    const user = userEvent.setup();
    const autoTitle = "自動生成されたタイトル";
    const autoTitleSession = { ...sampleSession, title: autoTitle };

    mockListSessions
      .mockResolvedValueOnce({ sessions: [sampleSession] })
      .mockResolvedValue({ sessions: [autoTitleSession] });

    mockStreamMessage.mockImplementation(
      async (sessionId, content, onEvent) => {
        onEvent({ type: "text", delta: "応答テキスト" });
        onEvent({
          type: "done",
          message: {
            message_id: "msg_3",
            session_id: sessionId,
            sequence: 3,
            role: "assistant",
            content: "応答テキスト",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_auto_title",
            session_id: sessionId,
            user_message_id: "msg_2",
            assistant_message_id: "msg_3",
            status: "succeeded",
            used_tools: [],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
          session_title: autoTitle,
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
    expect(screen.getByText("明日の予定")).toBeInTheDocument();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "新しいトピックについて");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(screen.getByText("自動生成されたタイトル")).toBeInTheDocument();
    });
  });

  it("keeps current session selected after stream completes even when session list order changes (regression)", async () => {
    const user = userEvent.setup();
    const otherSession = {
      ...sampleSession,
      session_id: "asess_789",
      title: "別の会話",
      pinned_at: null,
      updated_at: "2026-08-20T00:00:00Z",
    };
    const pinnedSession = {
      ...sampleSession,
      session_id: "asess_999",
      title: "ピン留めされた会話",
      pinned_at: "2026-08-25T00:00:00Z",
      updated_at: "2026-08-25T00:00:00Z",
    };

    // Initial load: selected is sampleSession (first)
    mockListSessions
      .mockResolvedValueOnce({ sessions: [sampleSession, otherSession] })
      // After stream, pinned session appears first due to ordering
      .mockResolvedValue({ sessions: [pinnedSession, sampleSession, otherSession] });

    // Ensure detail for stream session returns consistent messages
    mockGetSessionDetail.mockImplementation(async (sessionId: string) => {
      if (sessionId === sampleSession.session_id) {
        return {
          session: sampleSession,
          agent: sampleAgent,
          messages: [
            {
              message_id: "msg_1",
              session_id: sampleSession.session_id,
              sequence: 1,
              role: "user",
              content: "こんにちは",
              created_at: "2026-08-20T00:00:00Z",
            },
            {
              message_id: "msg_2",
              session_id: sampleSession.session_id,
              sequence: 2,
              role: "assistant",
              content: "こんにちは！何かお手伝いできますか？",
              created_at: "2026-08-20T00:00:01Z",
            },
            {
              message_id: "msg_3",
              session_id: sampleSession.session_id,
              sequence: 3,
              role: "assistant",
              content: "ストリーム完了後の確定本文",
              created_at: new Date().toISOString(),
            },
          ],
          runs: [],
        };
      }
      if (sessionId === pinnedSession.session_id) {
        return {
          session: pinnedSession,
          agent: sampleAgent,
          messages: [
            {
              message_id: "msg_pinned_1",
              session_id: pinnedSession.session_id,
              sequence: 1,
              role: "assistant",
              content: "ピン留め会話の内容",
              created_at: "2026-08-25T00:00:00Z",
            },
          ],
          runs: [],
        };
      }
      return {
        session: otherSession,
        agent: sampleAgent,
        messages: [],
        runs: [],
      };
    });

    mockStreamMessage.mockImplementation(
      async (sessionId, _content, onEvent) => {
        onEvent({ type: "text", delta: "応答" });
        onEvent({
          type: "done",
          message: {
            message_id: "msg_3",
            session_id: sessionId,
            sequence: 3,
            role: "assistant",
            content: "ストリーム完了後の確定本文",
            created_at: new Date().toISOString(),
          },
          run: {
            run_id: "arun_stream_regression",
            session_id: sessionId,
            user_message_id: "msg_2",
            assistant_message_id: "msg_3",
            status: "succeeded",
            used_tools: [],
            created_hitl_run_ids: [],
            error_message: null,
            started_at: "",
            finished_at: "",
          },
          hitl_run_ids: [],
        });
      }
    );

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("こんにちは！何かお手伝いできますか？")).toBeInTheDocument();
    // Verify initial selection is sampleSession
    expect(screen.getByText("明日の予定").closest('[data-selected="true"]')).not.toBeNull();

    const input = screen.getByPlaceholderText(/^メッセージを入力/);
    await user.type(input, "テスト");
    await user.click(screen.getByRole("button", { name: "送信" }));

    await waitFor(() => {
      expect(screen.getByText("ストリーム完了後の確定本文")).toBeInTheDocument();
    });

    // After stream, the pinned session is now first, but selection must stay on original
    await waitFor(() => {
      expect(mockListSessions).toHaveBeenCalledTimes(2);
    });
    // Pinned session exists in list but must NOT be selected
    const pinnedRow = screen.getByText("ピン留めされた会話").closest('[data-selected]');
    expect(pinnedRow?.getAttribute("data-selected")).toBe("false");
    const selectedRow = screen.getByText("明日の予定").closest('[data-selected]');
    expect(selectedRow?.getAttribute("data-selected")).toBe("true");
    // Ensure pinned conversation content is not shown
    expect(screen.queryByText("ピン留め会話の内容")).not.toBeInTheDocument();
  });

  it("shows pinned state on the pin button when agent is pinned", async () => {
    const pinnedAgent = { ...sampleAgent, pinned_at: "2026-08-25T00:00:00Z" };
    mockListAgents.mockResolvedValue({ agents: [pinnedAgent] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockListAgents).toHaveBeenCalled();
    });

    const pinButton = screen.getByRole("button", { name: "ピン留めを解除" });
    expect(pinButton).toHaveAttribute("aria-pressed", "true");
  });

  describe("Command Palette (/ command)", () => {
    const sampleTemplates = [
      {
        template_id: "tpl_1",
        agent_id: "agent_123",
        name: "挨拶テンプレート",
        content: "こんにちは！お世話になっております。",
        display_order: 0,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      },
      {
        template_id: "tpl_2",
        agent_id: "agent_123",
        name: "template 週次報告",
        content: "今週の進捗報告をお送りします。",
        display_order: 1,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      },
      {
        template_id: "tpl_3",
        agent_id: "agent_123",
        name: "ミーティング準備",
        content: "アジェンダと資料を準備しました。",
        display_order: 2,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      },
    ];

    beforeEach(() => {
      mockListTemplates.mockResolvedValue({ templates: sampleTemplates });
    });

    it("opens palette and displays all templates (max 8) when input starts with '/' alone", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = await screen.findByPlaceholderText(/^メッセージを入力/);
      await user.type(input, "/");

      const palette = await screen.findByTestId("agent-command-palette");
      expect(palette).toBeInTheDocument();
      expect(within(palette).getByText("挨拶テンプレート")).toBeInTheDocument();
      expect(within(palette).getByText("template 週次報告")).toBeInTheDocument();
      expect(within(palette).getByText("ミーティング準備")).toBeInTheDocument();
    });

    it("filters candidates with short form /name, explicit form /template name, and /template without space", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = await screen.findByPlaceholderText(/^メッセージを入力/);

      // Short form filtering: /挨拶
      await user.type(input, "/挨拶");
      const paletteShort = await screen.findByTestId("agent-command-palette");
      expect(within(paletteShort).getByText("挨拶テンプレート")).toBeInTheDocument();
      expect(within(paletteShort).queryByText("ミーティング準備")).not.toBeInTheDocument();

      // Explicit form filtering: /template 週次
      await user.clear(input);
      await user.type(input, "/template 週次");
      const paletteExplicit = await screen.findByTestId("agent-command-palette");
      expect(within(paletteExplicit).getByText("template 週次報告")).toBeInTheDocument();
      expect(within(paletteExplicit).queryByText("挨拶テンプレート")).not.toBeInTheDocument();

      // /template without trailing space treats 'template' as name filter
      await user.clear(input);
      await user.type(input, "/template");
      const paletteTemplateNoSpace = await screen.findByTestId("agent-command-palette");
      expect(within(paletteTemplateNoSpace).getByText("template 週次報告")).toBeInTheDocument();
      expect(within(paletteTemplateNoSpace).queryByText("ミーティング準備")).not.toBeInTheDocument();

      // No match shows empty state
      await user.clear(input);
      await user.type(input, "/xyz_no_match");
      const paletteEmpty = await screen.findByTestId("agent-command-palette");
      expect(within(paletteEmpty).getByText("該当するテンプレートがありません")).toBeInTheDocument();
    });

    it("selects candidate on click, replacing input text with template body and keeping focus in textarea", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = (await screen.findByPlaceholderText(/^メッセージを入力/)) as HTMLTextAreaElement;
      await user.type(input, "/");

      const palette = await screen.findByTestId("agent-command-palette");
      await user.click(within(palette).getByText("挨拶テンプレート"));

      expect(input.value).toBe("こんにちは！お世話になっております。");
      expect(screen.queryByTestId("agent-command-palette")).not.toBeInTheDocument();
      expect(document.activeElement).toBe(input);
    });

    it("reliably closes command palette when selecting a template whose content starts with '/'", async () => {
      const user = userEvent.setup();
      const slashTemplate = {
        template_id: "tpl_slash",
        agent_id: "agent_123",
        name: "Slash Content Template",
        content: "/slash_command_content",
        display_order: 0,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      };
      mockListTemplates.mockResolvedValue({ templates: [slashTemplate] });

      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = (await screen.findByPlaceholderText(/^メッセージを入力/)) as HTMLTextAreaElement;
      await user.type(input, "/");

      const palette = await screen.findByTestId("agent-command-palette");
      await user.click(within(palette).getByText("Slash Content Template"));

      expect(input.value).toBe("/slash_command_content");
      expect(screen.queryByTestId("agent-command-palette")).not.toBeInTheDocument();
    });

    it("supports ArrowUp/ArrowDown wrap-around, Enter selecting without sending, and Escape closing", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = (await screen.findByPlaceholderText(/^メッセージを入力/)) as HTMLTextAreaElement;
      await user.type(input, "/");

      await screen.findByTestId("agent-command-palette");

      // Initially index 0 ("挨拶テンプレート") is selected.
      // ArrowDown -> index 1 ("template 週次報告")
      fireEvent.keyDown(input, { key: "ArrowDown" });
      // ArrowDown -> index 2 ("ミーティング準備")
      fireEvent.keyDown(input, { key: "ArrowDown" });
      // ArrowDown -> wraps around to index 0 ("挨拶テンプレート")
      fireEvent.keyDown(input, { key: "ArrowDown" });
      // ArrowUp -> wraps around to index 2 ("ミーティング準備")
      fireEvent.keyDown(input, { key: "ArrowUp" });

      // Enter selects highlighted candidate (index 2: "ミーティング準備")
      fireEvent.keyDown(input, { key: "Enter" });

      expect(input.value).toBe("アジェンダと資料を準備しました。");
      expect(mockStreamMessage).not.toHaveBeenCalled();
      expect(screen.queryByTestId("agent-command-palette")).not.toBeInTheDocument();

      // Escape closes palette
      await user.clear(input);
      await user.type(input, "/");
      expect(await screen.findByTestId("agent-command-palette")).toBeInTheDocument();

      fireEvent.keyDown(input, { key: "Escape" });
      expect(screen.queryByTestId("agent-command-palette")).not.toBeInTheDocument();
    });

    it("immediately sends input when Ctrl+Enter is pressed while palette is open", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      const input = await screen.findByPlaceholderText(/^メッセージを入力/);
      await user.type(input, "/hello");

      expect(await screen.findByTestId("agent-command-palette")).toBeInTheDocument();

      fireEvent.keyDown(input, { key: "Enter", ctrlKey: true });

      await waitFor(() => {
        expect(mockStreamMessage).toHaveBeenCalledWith(
          "asess_456",
          "/hello",
          expect.any(Function),
          expect.any(Object),
          undefined
        );
      });
    });

    it("confirms existing '+ -> template' entry point continues to work", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );

      await waitFor(() => {
        expect(mockGetSessionDetail).toHaveBeenCalled();
      });

      await user.click(screen.getByRole("button", { name: "追加メニュー" }));
      await user.click(screen.getByRole("button", { name: "テンプレート" }));

      const selector = await screen.findByTestId("agent-template-selector");
      await user.click(within(selector).getByText("挨拶テンプレート"));

      const input = screen.getByPlaceholderText(/^メッセージを入力/) as HTMLTextAreaElement;
      expect(input.value).toBe("こんにちは！お世話になっております。");
    });
  });

  it("renders delegate target agent selector when agent_delegate tool is checked", async () => {
    const user = userEvent.setup();
    const otherAgent = {
      ...sampleAgent,
      agent_id: "agent_888",
      name: "サブワーカー",
    };
    const delegateTool = {
      tool_id: "agent_delegate",
      name: "エージェント委譲",
      description: "別エージェントにタスクを委譲します",
    };

    mockListAgents.mockResolvedValue({ agents: [sampleAgent, otherAgent] });
    mockListTools.mockResolvedValue({ tools: [...sampleTools, delegateTool] });

    render(
      <MemoryRouter>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(mockGetSessionDetail).toHaveBeenCalled();
    });

    await user.click(screen.getByRole("button", { name: "設定編集" }));

    // Check agent_delegate checkbox
    const delegateCheckbox = screen.getByRole("checkbox", { name: /エージェント委譲/i });
    expect(delegateCheckbox).not.toBeChecked();

    await user.click(delegateCheckbox);

    // Section "許可する委譲先エージェント" should appear with target agent "サブワーカー"
    expect(screen.getByText("許可する委譲先エージェント")).toBeInTheDocument();
    expect(screen.getAllByText("サブワーカー").length).toBeGreaterThanOrEqual(2);
  });

  describe("エージェントID（CLI用）の表示とコピー", () => {
    const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

    afterEach(() => {
      if (originalClipboard) {
        Object.defineProperty(navigator, "clipboard", originalClipboard);
      } else {
        // @ts-expect-error - restore jsdom default (no clipboard)
        delete navigator.clipboard;
      }
    });

    async function openEditForm(user: ReturnType<typeof userEvent.setup>) {
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );
      await waitFor(() => {
        expect(mockGetSessionDetail).toHaveBeenCalled();
      });
      await user.click(screen.getByRole("button", { name: "設定編集" }));
      expect(screen.getByText("エージェント設定編集")).toBeInTheDocument();
    }

    it("shows the agent ID with a copy button and copies it to the clipboard", async () => {
      const user = userEvent.setup();
      const writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText },
      });

      await openEditForm(user);

      expect(screen.getByText("エージェントID（CLI用）")).toBeInTheDocument();
      expect(screen.getByTestId("agent-id-value")).toHaveTextContent("agent_123");

      const copyButton = screen.getByRole("button", { name: "エージェントIDをコピー" });
      expect(copyButton).toHaveAttribute("title", "エージェントIDをコピー");

      await user.click(copyButton);

      await waitFor(() => {
        expect(writeText).toHaveBeenCalledWith("agent_123");
      });
      expect(await screen.findByText("コピーしました")).toBeInTheDocument();
    });

    it("shows an error message when copying the agent ID fails", async () => {
      const user = userEvent.setup();
      const writeText = vi.fn().mockRejectedValue(new Error("denied"));
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText },
      });

      await openEditForm(user);

      await user.click(screen.getByRole("button", { name: "エージェントIDをコピー" }));

      await waitFor(() => {
        expect(writeText).toHaveBeenCalledWith("agent_123");
      });
      expect(
        await screen.findByText("IDのコピーに失敗しました。手動で選択してコピーしてください。")
      ).toBeInTheDocument();
    });

    it("shows an error message when the clipboard API is unavailable", async () => {
      const user = userEvent.setup();
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: undefined,
      });

      await openEditForm(user);

      await user.click(screen.getByRole("button", { name: "エージェントIDをコピー" }));

      expect(
        await screen.findByText("IDのコピーに失敗しました。手動で選択してコピーしてください。")
      ).toBeInTheDocument();
    });

    it("does not show the agent ID copy UI in the create form", async () => {
      const user = userEvent.setup();
      render(
        <MemoryRouter>
          <AgentsPage />
        </MemoryRouter>
      );
      await waitFor(() => {
        expect(mockGetSessionDetail).toHaveBeenCalled();
      });

      await user.click(screen.getAllByRole("button", { name: "＋ 新規作成" })[0]);
      expect(screen.getByText("新規エージェント作成")).toBeInTheDocument();
      expect(screen.queryByText("エージェントID（CLI用）")).not.toBeInTheDocument();
      expect(screen.queryByTestId("copy-agent-id")).not.toBeInTheDocument();
    });
  });
});
