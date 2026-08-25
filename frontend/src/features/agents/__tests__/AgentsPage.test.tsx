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
  localStorage.clear();
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

    expect(localStorage.getItem("agent-draft:asess_456")).toBeNull();
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 250)));

    const saved = JSON.parse(localStorage.getItem("agent-draft:asess_456") || "{}");
    expect(saved.text).toBe("下書き保存テスト");
    expect(saved.attachments).toEqual([]);
  });

  it("loads a saved draft when the session is selected", async () => {
    localStorage.setItem(
      "agent-draft:asess_456",
      JSON.stringify({
        text: "復元される下書き",
        attachments: [],
        savedAt: new Date().toISOString(),
      })
    );

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
    await act(() => new Promise((resolve) => window.setTimeout(resolve, 250)));
    expect(localStorage.getItem("agent-draft:asess_456")).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => {
      expect(localStorage.getItem("agent-draft:asess_456")).toBeNull();
    });
  });
});
