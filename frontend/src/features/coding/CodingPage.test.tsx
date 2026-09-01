import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import CodingPage from "./CodingPage";
import * as codingApi from "../../api/coding";

vi.mock("../../api/coding", () => ({
  listCodingProjects: vi.fn(),
  listCodingSessions: vi.fn(),
  createCodingSession: vi.fn(),
  getCodingSessionDetail: vi.fn(),
  deleteCodingSession: vi.fn(),
  cancelCodingRun: vi.fn(),
  streamCodingMessage: vi.fn(),
  getGitStatus: vi.fn(),
  getCodingDefaults: vi.fn(),
  updateCodingDefaults: vi.fn(),
  updateCodingSessionTools: vi.fn(),
}));

const mockProjectItem: codingApi.CodingProjectItem = {
  project: {
    project_id: 1,
    normalized_name: "test-app",
    display_name: "Test App",
    domain: "work",
    status: "active",
    keywords: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  is_valid_git_repo: true,
  repo_path: "/app/test_repo",
  error_message: null,
};

const mockSession: codingApi.CodingSession = {
  session_id: "cses_111",
  project_id: 1,
  backend: "codex",
  repo_path: "/app/test_repo",
  external_session_id: null,
  title: "新規セッション",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("CodingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.mocked(codingApi.getGitStatus).mockResolvedValue({
      branch: "main",
      ahead: 2,
      behind: 1,
      insertions: 15,
      deletions: 3,
    });
    vi.mocked(codingApi.listCodingProjects).mockResolvedValue([mockProjectItem]);
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
        { tool_id: "run_shell", name: "任意シェル実行", description: "シェル実行" },
      ],
      messages: [
        {
          message_id: "cmsg_1",
          session_id: "cses_111",
          sequence: 1,
          role: "user",
          content: "こんにちは",
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          message_id: "cmsg_2",
          session_id: "cses_111",
          sequence: 2,
          role: "orchestrator",
          content: "こんにちは！何かお手伝いしましょうか？",
          created_at: "2026-01-01T00:01:00Z",
        },
      ],
      active_run: null,
      latest_run: null,
    });
  });

  beforeEach(() => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it("renders 3 panes and displays projects, sessions, and messages", async () => {
    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
      expect(screen.getAllByText("新規セッション").length).toBeGreaterThan(0);
      expect(screen.getByText("こんにちは！何かお手伝いしましょうか？")).toBeInTheDocument();
    });
  });

  it("displays git status in header and refreshes upon receiving SSE response", async () => {
    vi.mocked(codingApi.getGitStatus).mockResolvedValueOnce({
      branch: "feature/test",
      ahead: 1,
      behind: 0,
      insertions: 5,
      deletions: 2,
    });

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("feature/test")).toBeInTheDocument();
      expect(screen.getByText("↑1 ↓0")).toBeInTheDocument();
      expect(screen.getByText("+5")).toBeInTheDocument();
      expect(screen.getByText("-2")).toBeInTheDocument();
    });
  });

  it("opens new session modal and creates a session without manually entering a title", async () => {
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_222",
      title: "新しいコーディングセッション",
    });

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    expect(screen.getByText("新規コーディングセッション作成")).toBeInTheDocument();

    // Do not fill in title input
    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "codex", undefined);
    });
  });

  it("updates session title when coding CLI response event contains session_title", async () => {
    vi.mocked(codingApi.streamCodingMessage).mockImplementation(
      async (_sessionId, _content, onEvent) => {
        onEvent({ event: "start", run_id: "crun_999", is_dirty: false, dirty_summary: null });
        onEvent({
          event: "done",
          run_id: "crun_999",
          status: "completed",
          session_title: "CLI生成タイトル",
        });
      },
    );

    // Mock getCodingSessionDetail to reflect updated session title on refetch
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: {
        ...mockSession,
        title: "CLI生成タイトル",
      },
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
      messages: [],
      active_run: null,
      latest_run: null,
    });

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "タイトル生成" } });

    const sendBtn = screen.getByRole("button", { name: "送信" });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(screen.getAllByText("CLI生成タイトル").length).toBeGreaterThan(0);
    });
  });

  it("handles message streaming lifecycle and refetches session detail on completion", async () => {
    vi.mocked(codingApi.streamCodingMessage).mockImplementation(
      async (_sessionId, _content, onEvent) => {
        onEvent({ event: "start", run_id: "crun_999", is_dirty: false, dirty_summary: null });
        onEvent({ event: "orchestrator_start", phase: "initial" });
        onEvent({
          event: "orchestrator_message",
          phase: "initial",
          message: {
            message_id: "cmsg_orch1",
            session_id: "cses_111",
            sequence: 3,
            role: "orchestrator",
            content: "オーケストレーター判断1",
            created_at: "2026-01-01T00:02:00Z",
          },
        });
        onEvent({ event: "worker_start", attempt: 1, backend: "codex", prompt: "codex test" });
        onEvent({
          event: "worker_done",
          attempt: 1,
          message: {
            message_id: "cmsg_work1",
            session_id: "cses_111",
            sequence: 4,
            role: "worker",
            content: "Worker output text",
            created_at: "2026-01-01T00:03:00Z",
          },
          exit_code: 0,
          error: null,
        });
        onEvent({ event: "orchestrator_start", phase: "review" });
        onEvent({
          event: "orchestrator_message",
          phase: "review",
          message: {
            message_id: "cmsg_orch2",
            session_id: "cses_111",
            sequence: 5,
            role: "orchestrator",
            content: "オーケストレーター最終報告",
            created_at: "2026-01-01T00:04:00Z",
          },
        });
        onEvent({ event: "done", run_id: "crun_999", status: "completed" });
      },
    );

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "テスト実行してください" } });

    const sendBtn = screen.getByRole("button", { name: "送信" });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(codingApi.streamCodingMessage).toHaveBeenCalledWith(
        "cses_111",
        "テスト実行してください",
        expect.any(Function),
      );
      expect(codingApi.getCodingSessionDetail).toHaveBeenCalledWith("cses_111");
    });
  });

  it("allows cancelling active run", async () => {
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
      messages: [],
      active_run: {
        run_id: "crun_active",
        session_id: "cses_111",
        user_message_id: "cmsg_1",
        orchestrator_message_id: null,
        worker_message_id: null,
        status: "running",
        dirty_tree_at_start: null,
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        finished_at: null,
      },
      latest_run: null,
    });
    vi.mocked(codingApi.cancelCodingRun).mockResolvedValue({
      status: "cancel_signalled",
      run_id: "crun_active",
    });

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("キャンセル")).toBeInTheDocument();
    });

    const cancelBtn = screen.getByRole("button", { name: "キャンセル" });
    fireEvent.click(cancelBtn);

    await waitFor(() => {
      expect(codingApi.cancelCodingRun).toHaveBeenCalledWith("crun_active");
    });
  });

  it("shows mode-aware placeholder for 'enter' and 'newline'", async () => {
    render(<CodingPage />);
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    expect(
      screen.getByPlaceholderText("指示・質問を入力…（Enterで送信 / Shift+Enterで改行）"),
    ).toBeInTheDocument();

    localStorage.setItem("obsidian-ai-hub:chat-send-mode", "newline");
    window.dispatchEvent(new Event("chat-send-mode-changed"));

    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("指示・質問を入力…（Enterで改行 / Ctrl+Enterで送信）"),
      ).toBeInTheDocument(),
    );
  });

  it("sends on Enter when mode is 'enter', but not on Shift+Enter", async () => {
    vi.mocked(codingApi.streamCodingMessage).mockResolvedValue(undefined);
    render(<CodingPage />);
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "enter-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(codingApi.streamCodingMessage).toHaveBeenCalled());

    vi.mocked(codingApi.streamCodingMessage).mockClear();
    fireEvent.change(textarea, { target: { value: "shift-enter" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    await waitFor(() => new Promise((r) => setTimeout(r, 50)));
    expect(codingApi.streamCodingMessage).not.toHaveBeenCalled();
  });

  it("does not send on plain Enter when mode is 'newline', but sends on Ctrl+Enter and Cmd+Enter", async () => {
    localStorage.setItem("obsidian-ai-hub:chat-send-mode", "newline");
    vi.mocked(codingApi.streamCodingMessage).mockResolvedValue(undefined);
    render(<CodingPage />);
    await waitFor(() =>
      expect(
        screen.getByPlaceholderText("指示・質問を入力…（Enterで改行 / Ctrl+Enterで送信）"),
      ).toBeInTheDocument(),
    );
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで改行 / Ctrl+Enterで送信）",
    );

    fireEvent.change(textarea, { target: { value: "no-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    await waitFor(() => new Promise((r) => setTimeout(r, 30)));
    expect(codingApi.streamCodingMessage).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "ctrl-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(codingApi.streamCodingMessage).toHaveBeenCalled());
    vi.mocked(codingApi.streamCodingMessage).mockClear();

    fireEvent.change(textarea, { target: { value: "meta-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    await waitFor(() => expect(codingApi.streamCodingMessage).toHaveBeenCalled());
  });

  it("does not send while composing (IME via keyCode 229)", async () => {
    vi.mocked(codingApi.streamCodingMessage).mockResolvedValue(undefined);
    render(<CodingPage />);
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "composing" } });
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 229 } as any);
    await waitFor(() => new Promise((r) => setTimeout(r, 30)));
    expect(codingApi.streamCodingMessage).not.toHaveBeenCalled();
  });

  it("opens conversation settings modal and updates session tools", async () => {
    vi.mocked(codingApi.updateCodingSessionTools).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: true,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
        { tool_id: "run_shell", name: "任意シェル実行", description: "シェル実行" },
      ],
      messages: [],
      active_run: null,
      latest_run: null,
    });

    render(<CodingPage />);
    await waitFor(() => expect(screen.getByText("会話設定 ⚙")).toBeInTheDocument());

    const settingsBtn = screen.getByRole("button", { name: "会話設定 ⚙" });
    fireEvent.click(settingsBtn);

    expect(screen.getByText("会話の利用可能ツール設定")).toBeInTheDocument();

    const saveBtn = screen.getByRole("button", { name: "保存" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(codingApi.updateCodingSessionTools).toHaveBeenCalledWith(
        "cses_111",
        ["web_search", "vault_search"],
      );
    });
  });

  it("opens user default tools modal and updates defaults", async () => {
    vi.mocked(codingApi.getCodingDefaults).mockResolvedValue({
      default_tool_ids: ["web_search", "vault_search"],
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
    });
    vi.mocked(codingApi.updateCodingDefaults).mockResolvedValue({
      default_tool_ids: ["web_search"],
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
    });

    render(<CodingPage />);
    await waitFor(() => expect(screen.getByText("既定設定")).toBeInTheDocument());

    const defaultsBtn = screen.getByRole("button", { name: "既定設定" });
    fireEvent.click(defaultsBtn);

    await waitFor(() => {
      expect(screen.getByText("ユーザー既定の利用可能ツール設定")).toBeInTheDocument();
    });

    const saveBtn = screen.getByRole("button", { name: "既定値として保存" });
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(codingApi.updateCodingDefaults).toHaveBeenCalledWith(["web_search", "vault_search"]);
    });
  });
});
