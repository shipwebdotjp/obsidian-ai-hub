import { render, screen, fireEvent, waitFor, within, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import CodingPage from "./CodingPage";
import * as codingApi from "../../api/coding";
import * as clientApi from "../../api/client";

vi.mock("../../api/client", () => ({
  getHitlRun: vi.fn(),
  submitHitlAnswer: vi.fn(),
  cancelHitlRun: vi.fn(),
}));

vi.mock("../../api/coding", () => ({
  listCodingProjects: vi.fn(),
  listCodingSessions: vi.fn(),
  createCodingSession: vi.fn(),
  getCodingSessionDetail: vi.fn(),
  deleteCodingSession: vi.fn(),
  cancelCodingRun: vi.fn(),
  startCodingRun: vi.fn(),
  subscribeCodingRunEvents: vi.fn(),
  getGitStatus: vi.fn(),
  getCodingDefaults: vi.fn(),
  getCodingConfig: vi.fn(),
  updateCodingDefaults: vi.fn(),
  updateCodingSessionTools: vi.fn(),
  updateCodingSessionTitle: vi.fn(),
  getSlashCandidates: vi.fn(),
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

function mockCodingRun(overrides: Partial<codingApi.CodingRun> = {}): codingApi.CodingRun {
  return {
    run_id: "crun_1",
    session_id: "cses_111",
    user_message_id: "cmsg_1",
    orchestrator_message_id: null,
    worker_message_id: null,
    status: "queued",
    hitl_run_id: null,
    dirty_tree_at_start: null,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

type Envelope = { eventId: number; data: Record<string, unknown> };

function mockStartSubscribeSuccess(
  envelopes: Envelope[],
  opts: { runId?: string; sessionId?: string } = {},
) {
  const runId = opts.runId ?? "crun_999";
  const sessionId = opts.sessionId ?? "cses_111";
  vi.mocked(codingApi.startCodingRun).mockResolvedValue({
    run: mockCodingRun({ run_id: runId, session_id: sessionId, status: "queued" }),
  });
  vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(async (_runId, subOpts) => {
    for (const env of envelopes) {
      (subOpts as { onEnvelope: (e: Envelope) => void }).onEnvelope(env);
    }
  });
  return { runId, sessionId };
}

function renderPage(initialEntries: string[] = ["/coding"]) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <CodingPage />
    </MemoryRouter>,
  );
}

describe("CodingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    vi.mocked(codingApi.getGitStatus).mockResolvedValue({
      branch: "main",
      ahead: 2,
      behind: 1,
      insertions: 15,
      deletions: 3,
    });
    vi.mocked(codingApi.getSlashCandidates).mockResolvedValue({
      candidates: [{ kind: "skill", name: "pdftomd", description: "PDF to MD" }],
      has_skills_tool: true,
    });
    vi.mocked(codingApi.getCodingConfig).mockResolvedValue({ default_backend: "opencode" });
    vi.mocked(codingApi.listCodingProjects).mockResolvedValue([mockProjectItem]);
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession]);
    vi.mocked(codingApi.subscribeCodingRunEvents).mockResolvedValue(undefined);
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
      orchestrator_tool_calls: [],
    });
  });

  beforeEach(() => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  });

  it("renders 2 panes and displays projects, sessions, and messages", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
      expect(screen.getAllByText("新規セッション").length).toBeGreaterThan(0);
      expect(screen.getByText("こんにちは！何かお手伝いしましょうか？")).toBeInTheDocument();
    });
  });

  it("collapses left pane when collapse button is clicked and expands when expand button is clicked", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const collapseBtn = screen.getByRole("button", { name: "サイドバーを畳む" });
    expect(collapseBtn).toHaveClass("text-slate-500", "hover:bg-slate-100");
    fireEvent.click(collapseBtn);

    expect(screen.queryByText("プロジェクト")).not.toBeInTheDocument();

    const expandBtn = screen.getByRole("button", { name: "サイドバーを展開" });
    fireEvent.click(expandBtn);

    await waitFor(() => {
      expect(screen.getByText("プロジェクト")).toBeInTheDocument();
    });
  });

  it("renders '既定設定' and '+ 新規' buttons with matching sizing and styling", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const defaultsBtn = screen.getByRole("button", { name: "既定設定" });
    const newSessionBtn = screen.getByRole("button", { name: "+ 新規" });

    expect(defaultsBtn).toHaveClass("border", "border-slate-300", "bg-white", "text-slate-700", "hover:bg-slate-50", "px-3", "py-1", "text-sm", "font-medium");
    expect(newSessionBtn).toHaveClass("px-3", "py-1", "text-sm", "font-medium");
  });

  it("allows expanding left pane even when no session is selected", async () => {
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const collapseBtn = screen.getByRole("button", { name: "サイドバーを畳む" });
    fireEvent.click(collapseBtn);

    expect(screen.getByText("セッションを選択するか、新規セッションを作成してください")).toBeInTheDocument();

    const expandBtn = screen.getByRole("button", { name: "サイドバーを展開" });
    fireEvent.click(expandBtn);

    await waitFor(() => {
      expect(screen.getByText("プロジェクト")).toBeInTheDocument();
    });
  });

  it("renders dedicated card for cli_request role and diagnostics in worker card", async () => {
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
      messages: [
        {
          message_id: "cmsg_1",
          session_id: "cses_111",
          sequence: 1,
          role: "user",
          content: "コード調査をして",
          created_at: "2026-01-01T00:00:00Z",
        },
        {
          message_id: "cmsg_2",
          session_id: "cses_111",
          sequence: 2,
          role: "cli_request",
          content: "git status && pytest",
          created_at: "2026-01-01T00:01:00Z",
        },
        {
          message_id: "cmsg_3",
          session_id: "cses_111",
          sequence: 3,
          role: "worker",
          content: "1 passed",
          created_at: "2026-01-01T00:02:00Z",
        },
      ],
      active_run: null,
      latest_run: {
        run_id: "crun_diag",
        session_id: "cses_111",
        user_message_id: "cmsg_1",
        orchestrator_message_id: null,
        hitl_run_id: null,
        worker_message_id: "cmsg_3",
        status: "completed",
        dirty_tree_at_start: null,
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        finished_at: "2026-01-01T00:02:00Z",
        diagnostics: {
          cwd: "/app/test_repo",
          requested_session_id: "ses_req123",
          returned_session_id: "ses_ret456",
          tool_call_count: 3,
          tool_failure_count: 0,
          structured_error: null,
          auto_rejected_permission: false,
          exit_code: 0,
          model: "既定（Global default）",
          variant: "なし",
        },
      },
      orchestrator_tool_calls: [],
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("cli-request-card")).toBeInTheDocument();
      expect(screen.getByText("git status && pytest")).toBeInTheDocument();
      const diagCard = screen.getByTestId("worker-diagnostics");
      expect(diagCard).toBeInTheDocument();
      expect(within(diagCard).getByText("/app/test_repo")).toBeInTheDocument();
      expect(screen.getByText("ses_req123")).toBeInTheDocument();
      expect(screen.getByText("ses_ret456")).toBeInTheDocument();
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

    renderPage();

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

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    expect(screen.getByText("新規コーディングセッション作成")).toBeInTheDocument();

    // Do not fill in title input - default backend should be opencode (server default)
    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "opencode", undefined);
    });
  });

  it("initializes new session backend from server config (codex)", async () => {
    vi.mocked(codingApi.getCodingConfig).mockResolvedValue({ default_backend: "codex" });
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_223",
      title: "新しいコーディングセッション",
      backend: "codex",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    // Wait for config fetch to update backend selection
    await waitFor(() => {
      expect(codingApi.getCodingConfig).toHaveBeenCalled();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "codex", undefined);
    });
  });

  it("falls back to opencode when config fetch fails", async () => {
    vi.mocked(codingApi.getCodingConfig).mockRejectedValue(new Error("network error"));
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_224",
      title: "新しいコーディングセッション",
      backend: "opencode",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "opencode", undefined);
    });
  });

  it("preserves manually selected backend when config fetch resolves late", async () => {
    let resolveConfig: (v: any) => void;
    const configPromise = new Promise<codingApi.CodingConfig>((res) => {
      resolveConfig = res;
    });
    vi.mocked(codingApi.getCodingConfig).mockReturnValue(configPromise as any);
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_225",
      title: "新しいコーディングセッション",
      backend: "codex",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    // Manually select codex before config resolves
    const codexBtn = screen.getByText("Codex CLI").closest("button")!;
    fireEvent.click(codexBtn);

    // Now resolve config with opencode - should not overwrite manual selection
    resolveConfig!({ default_backend: "opencode" });
    await waitFor(() => {
      expect(codingApi.getCodingConfig).toHaveBeenCalled();
    });

    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "codex", undefined);
    });
  });

  it("falls back to opencode when config returns invalid backend", async () => {
    vi.mocked(codingApi.getCodingConfig).mockResolvedValue({ default_backend: "invalid" as any });
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_226",
      title: "新しいコーディングセッション",
      backend: "opencode",
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    // Wait for invalid config to be processed (should remain opencode)
    await waitFor(() => {
      expect(codingApi.getCodingConfig).toHaveBeenCalled();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "opencode", undefined);
    });
  });

  it("updates session title when coding CLI response event contains session_title", async () => {
    mockStartSubscribeSuccess([
      { eventId: 1, data: { event: "orchestrator_start", phase: "initial" } },
      { eventId: 2, data: { event: "done", run_id: "crun_999", status: "completed", session_title: "CLI生成タイトル" } },
    ]);

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
      orchestrator_tool_calls: [],
    });

    renderPage();

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
    mockStartSubscribeSuccess([
      { eventId: 1, data: { event: "orchestrator_start", phase: "initial" } },
      {
        eventId: 2,
        data: {
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
        },
      },
      { eventId: 3, data: { event: "worker_start", attempt: 1, backend: "codex", prompt: "codex test" } },
      {
        eventId: 4,
        data: {
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
        },
      },
      { eventId: 5, data: { event: "orchestrator_start", phase: "review" } },
      {
        eventId: 6,
        data: {
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
        },
      },
      { eventId: 7, data: { event: "done", run_id: "crun_999", status: "completed" } },
    ]);

    renderPage();

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
      expect(codingApi.startCodingRun).toHaveBeenCalledWith(
        "cses_111",
        "テスト実行してください",
        expect.any(String),
        null,
      );
      expect(codingApi.subscribeCodingRunEvents).toHaveBeenCalledWith(
        "crun_999",
        expect.objectContaining({ lastEventId: 0 }),
      );
      expect(codingApi.getCodingSessionDetail).toHaveBeenCalledWith("cses_111");
    });
  });

  it("triggers slash palette on typing / and sends selected skill with prompt text", async () => {
    mockStartSubscribeSuccess([
      { eventId: 1, data: { event: "done", run_id: "crun_slash", status: "completed" } },
    ]);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );

    // Type / to show slash candidates
    fireEvent.change(textarea, { target: { value: "/" } });

    await waitFor(() => {
      expect(screen.getByText("/pdftomd")).toBeInTheDocument();
      expect(screen.getByText("PDF to MD")).toBeInTheDocument();
    });

    // Click candidate
    fireEvent.click(screen.getByText("/pdftomd"));

    // Chip appears and input is cleared
    await waitFor(() => {
      const chipText = screen.getByText("/pdftomd");
      expect(chipText.parentElement).toHaveClass("text-blue-800");
      expect(textarea).toHaveValue("");
    });

    // Enter prompt text
    fireEvent.change(textarea, { target: { value: "PDFを変換してください" } });

    // Send
    const sendBtn = screen.getByRole("button", { name: "送信" });
    fireEvent.click(sendBtn);

    await waitFor(() => {
      expect(codingApi.startCodingRun).toHaveBeenCalledWith(
        "cses_111",
        "PDFを変換してください",
        expect.any(String),
        { kind: "skill", name: "pdftomd" },
      );
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
        hitl_run_id: null,
        worker_message_id: null,
        status: "running",
        dirty_tree_at_start: null,
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        finished_at: null,
      },
      latest_run: null,
      orchestrator_tool_calls: [],
    });
    vi.mocked(codingApi.cancelCodingRun).mockResolvedValue({
      status: "cancel_signalled",
      run_id: "crun_active",
    });
    // Active-run restore subscribes in the background; keep it pending.
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(() => new Promise(() => {}));

    renderPage();

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
    renderPage();
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
    mockStartSubscribeSuccess([{ eventId: 1, data: { event: "done", run_id: "crun_999", status: "completed" } }]);
    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "enter-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(codingApi.startCodingRun).toHaveBeenCalled());

    vi.mocked(codingApi.startCodingRun).mockClear();
    fireEvent.change(textarea, { target: { value: "shift-enter" } });
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    await waitFor(() => new Promise((r) => setTimeout(r, 50)));
    expect(codingApi.startCodingRun).not.toHaveBeenCalled();
  });

  it("does not send on plain Enter when mode is 'newline', but sends on Ctrl+Enter and Cmd+Enter", async () => {
    localStorage.setItem("obsidian-ai-hub:chat-send-mode", "newline");
    mockStartSubscribeSuccess([{ eventId: 1, data: { event: "done", run_id: "crun_999", status: "completed" } }]);
    renderPage();
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
    expect(codingApi.startCodingRun).not.toHaveBeenCalled();

    fireEvent.change(textarea, { target: { value: "ctrl-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(codingApi.startCodingRun).toHaveBeenCalled());
    vi.mocked(codingApi.startCodingRun).mockClear();

    fireEvent.change(textarea, { target: { value: "meta-send" } });
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    await waitFor(() => expect(codingApi.startCodingRun).toHaveBeenCalled());
  });

  it("does not send while composing (IME via keyCode 229)", async () => {
    vi.mocked(codingApi.startCodingRun).mockResolvedValue({ run: mockCodingRun() });
    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "composing" } });
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 229 } as any);
    await waitFor(() => new Promise((r) => setTimeout(r, 30)));
    expect(codingApi.startCodingRun).not.toHaveBeenCalled();
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
      orchestrator_tool_calls: [],
    });

    renderPage();
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

  it("updates session title from conversation settings modal", async () => {
    const updatedSession = { ...mockSession, title: "更新後タイトル" };
    vi.mocked(codingApi.updateCodingSessionTitle).mockResolvedValue({
      session: updatedSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    });
    vi.mocked(codingApi.updateCodingSessionTools).mockResolvedValue({
      session: updatedSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
        { tool_id: "vault_search", name: "Vault検索", description: "Vault内検索" },
      ],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("会話設定 ⚙")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "会話設定 ⚙" }));

    const titleInput = screen.getByLabelText("セッションタイトル");
    expect(titleInput).toHaveValue("新規セッション");
    fireEvent.change(titleInput, { target: { value: "更新後タイトル" } });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(codingApi.updateCodingSessionTitle).toHaveBeenCalledWith(
        "cses_111",
        "更新後タイトル",
      );
    });
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "更新後タイトル" })).toBeInTheDocument();
    });
  });

  it("rejects blank-only session title in conversation settings modal", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("会話設定 ⚙")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "会話設定 ⚙" }));

    const titleInput = screen.getByLabelText("セッションタイトル");
    fireEvent.change(titleInput, { target: { value: "   " } });

    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(screen.getByText("セッションタイトルを入力してください")).toBeInTheDocument();
    });
    expect(codingApi.updateCodingSessionTitle).not.toHaveBeenCalled();
    expect(codingApi.updateCodingSessionTools).not.toHaveBeenCalled();
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

    renderPage();
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

  it("opens mobile drawer and allows selecting projects and sessions", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const mobileBtn = screen.getByRole("button", { name: "プロジェクト / セッションを選択" });
    fireEvent.click(mobileBtn);

    expect(screen.getByRole("dialog", { name: "プロジェクトとセッションの選択" })).toBeInTheDocument();

    const closeBtn = screen.getByRole("button", { name: "サイドバーを閉じる" });
    fireEvent.click(closeBtn);

    expect(screen.queryByRole("dialog", { name: "プロジェクトとセッションの選択" })).not.toBeInTheDocument();
  });

  it("renders collapsible dirty tree banner when uncommitted changes exist", async () => {    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: {
        run_id: "crun_dirty",
        session_id: "cses_111",
        user_message_id: "cmsg_1",
        orchestrator_message_id: null,
        hitl_run_id: null,
        worker_message_id: null,
        status: "running",
        dirty_tree_at_start: " M src/App.tsx\n?? untracked.txt",
        error_message: null,
        started_at: "2026-01-01T00:00:00Z",
        finished_at: null,
      },
      latest_run: null,
      orchestrator_tool_calls: [],
    });
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(() => new Promise(() => {}));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("⚠️ 開始時に未コミットの変更があります")).toBeInTheDocument();
      expect(screen.getByText(/M src\/App\.tsx/)).toBeInTheDocument();
    });
  });

  it("saves the prompt draft per session and restores it on session switch", async () => {
    const secondSession: codingApi.CodingSession = {
      ...mockSession,
      session_id: "cses_222",
      title: "2つ目のセッション",
    };
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession, secondSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    }));

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Aの下書き" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBe("Aの下書き");

    // Switch to B: A's content must not leak, B starts empty.
    fireEvent.click(screen.getByText("2つ目のセッション"));
    await waitFor(() => expect(textarea.value).toBe(""));

    fireEvent.change(textarea, { target: { value: "Bの下書き" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));

    // Switch back to A: A's draft is restored, then B's as well.
    fireEvent.click(screen.getAllByText("新規セッション")[0]);
    await waitFor(() => expect(textarea.value).toBe("Aの下書き"));

    fireEvent.click(screen.getByText("2つ目のセッション"));
    await waitFor(() => expect(textarea.value).toBe("Bの下書き"));
  });

  it("flushes an unsaved draft to the old session on quick switch", async () => {
    const secondSession: codingApi.CodingSession = {
      ...mockSession,
      session_id: "cses_222",
      title: "2つ目のセッション",
    };
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession, secondSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    }));

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    ) as HTMLTextAreaElement;
    // Switch before the debounce fires: the pending text must land on A, not B.
    fireEvent.change(textarea, { target: { value: "Aの未保存入力" } });
    fireEvent.click(screen.getByText("2つ目のセッション"));
    await act(() => new Promise((r) => setTimeout(r, 650)));

    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBe("Aの未保存入力");
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_222")).toBeNull();
  });

  it("clears the session draft after a successful send", async () => {
    mockStartSubscribeSuccess([
      { eventId: 1, data: { event: "done", run_id: "crun_999", status: "completed" } },
    ]);

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "送信する下書き" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBe("送信する下書き");

    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => {
      expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBeNull();
      expect(textarea.value).toBe("");
    });
  });

  it("keeps the pre-send text as the session draft when send fails", async () => {
    vi.mocked(codingApi.startCodingRun).mockRejectedValue(new Error("送信失敗"));

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "失敗しても残る下書き" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));

    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => {
      expect(textarea.value).toBe("失敗しても残る下書き");
      expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBe(
        "失敗しても残る下書き",
      );
    });
  });

  it("does not touch session B when A's send completes after switching", async () => {
    const secondSession: codingApi.CodingSession = {
      ...mockSession,
      session_id: "cses_222",
      title: "2つ目のセッション",
    };
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession, secondSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : mockSession,
      effective_tool_ids: ["web_search", "vault_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    }));
    let capturedOnEnvelope: ((envelope: Envelope) => void) | null = null;
    vi.mocked(codingApi.startCodingRun).mockResolvedValue({
      run: mockCodingRun({ run_id: "crun_999", session_id: "cses_111" }),
    });
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(
      (_runId, opts) => {
        capturedOnEnvelope = (opts as { onEnvelope: (e: Envelope) => void }).onEnvelope;
        return new Promise(() => {});
      },
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    ) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "Aの送信文" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));

    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(capturedOnEnvelope).not.toBeNull());
    // Switch to B while A's stream is still running.
    fireEvent.click(screen.getByText("2つ目のセッション"));
    await waitFor(() => expect(textarea.value).toBe(""));

    fireEvent.change(textarea, { target: { value: "Bの入力中" } });
    await act(() => new Promise((r) => setTimeout(r, 650)));
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_222")).toBe("Bの入力中");

    // A's stream completes while viewing B.
    await act(async () => {
      capturedOnEnvelope?.({ eventId: 1, data: { event: "done", run_id: "crun_999", status: "completed" } });
    });

    // B's input and draft are untouched; only A's draft is deleted.
    expect(textarea.value).toBe("Bの入力中");
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_222")).toBe("Bの入力中");
    expect(sessionStorage.getItem("oaih:prompt-draft:coding:cses_111")).toBeNull();
  });

  it("renders live orchestrator tool call states during streaming", async () => {
    let capturedOnEnvelope: ((envelope: Envelope) => void) | null = null;
    vi.mocked(codingApi.startCodingRun).mockResolvedValue({
      run: mockCodingRun({ run_id: "crun_live", session_id: "cses_111" }),
    });
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(
      (_runId, opts) => {
        capturedOnEnvelope = (opts as { onEnvelope: (e: Envelope) => void }).onEnvelope;
        return new Promise(() => {});
      },
    );

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "ツール実行テスト" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(capturedOnEnvelope).not.toBeNull());

    // 1. Detected event -> "準備中…"
    act(() => {
      capturedOnEnvelope?.({
        eventId: 1,
        data: {
          event: "orchestrator_tool_call_detected",
          call_key: "1:1:0",
          tool_name: "web_search",
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
        },
      });
    });
    expect(screen.getByText("web_search")).toBeInTheDocument();
    expect(screen.getByText("準備中…")).toBeInTheDocument();

    // 2. Start event -> "実行中…"
    act(() => {
      capturedOnEnvelope?.({
        eventId: 2,
        data: {
          event: "orchestrator_tool_call_start",
          call_id: "cotc_live1",
          call_key: "1:1:0",
          tool_name: "web_search",
          args: { query: "vitest test" },
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
        },
      });
    });
    expect(screen.getAllByText("実行中…").length).toBeGreaterThan(0);

    // 3. End event -> "成功"
    act(() => {
      capturedOnEnvelope?.({
        eventId: 3,
        data: {
          event: "orchestrator_tool_call_end",
          call_id: "cotc_live1",
          call_key: "1:1:0",
          tool_name: "web_search",
          status: "succeeded",
          result: "検索完了結果",
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
        },
      });
    });
    expect(screen.getByText("成功")).toBeInTheDocument();
    expect(screen.getByText("検索完了結果")).toBeInTheDocument();
  });

  it("renders persisted orchestrator tool calls attached to orchestrator message", async () => {
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "web_search", name: "Web検索", description: "Tavily検索" },
      ],
      messages: [
        {
          message_id: "cmsg_u1",
          session_id: "cses_111",
          sequence: 1,
          role: "user",
          content: "Web検索して",
          created_at: "2026-01-01T00:00:00Z",
          run_id: "crun_100",
        },
        {
          message_id: "cmsg_o1",
          session_id: "cses_111",
          sequence: 2,
          role: "orchestrator",
          content: "検索結果をまとめました",
          created_at: "2026-01-01T00:01:00Z",
          run_id: "crun_100",
        },
      ],
      orchestrator_tool_calls: [
        {
          call_id: "cotc_persisted1",
          run_id: "crun_100",
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
          call_key: "1:1:0",
          orchestrator_message_id: "cmsg_o1",
          tool_name: "web_search",
          args: { query: "obsidian ai hub" },
          result: "保存済み検索結果",
          status: "succeeded",
          started_at: "2026-01-01T00:00:30Z",
        },
      ],
      active_run: null,
      latest_run: null,
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("ツール呼び出し 1件")).toBeInTheDocument();
      expect(screen.getByText("web_search")).toBeInTheDocument();
      expect(screen.getByText("成功")).toBeInTheDocument();
      expect(screen.getByText("保存済み検索結果")).toBeInTheDocument();
    });
  });

  it("renders unassociated interrupted or failed tool calls under '中断したオーケストレーター処理'", async () => {
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["run_shell"],
      has_custom_tools: false,
      available_tools: [
        { tool_id: "run_shell", name: "任意シェル実行", description: "シェル実行" },
      ],
      messages: [
        {
          message_id: "cmsg_u2",
          session_id: "cses_111",
          sequence: 1,
          role: "user",
          content: "コマンド実行して",
          created_at: "2026-01-01T00:00:00Z",
          run_id: "crun_interrupted",
        },
      ],
      orchestrator_tool_calls: [
        {
          call_id: "cotc_interrupted1",
          run_id: "crun_interrupted",
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
          call_key: "1:1:0",
          orchestrator_message_id: null,
          tool_name: "run_shell",
          args: { command: "ls -la" },
          result: null,
          status: "interrupted",
          error: "Interrupted due to server restart",
          started_at: "2026-01-01T00:00:30Z",
        },
      ],
      active_run: null,
      latest_run: {
        run_id: "crun_interrupted",
        session_id: "cses_111",
        user_message_id: "cmsg_u2",
        orchestrator_message_id: null,
        hitl_run_id: null,
        worker_message_id: null,
        status: "interrupted",
        dirty_tree_at_start: null,
        error_message: "Interrupted due to server restart",
        started_at: "2026-01-01T00:00:00Z",
        finished_at: "2026-01-01T00:01:00Z",
      },
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("中断したオーケストレーター処理 (1件)")).toBeInTheDocument();
      expect(screen.getByText("run_shell")).toBeInTheDocument();
      expect(screen.getByText("中断")).toBeInTheDocument();
      expect(screen.getByText("Interrupted due to server restart")).toBeInTheDocument();
    });
  });

  it("does not cancel the run on session switch or unmount (aborts subscription only)", async () => {
    const secondSession: codingApi.CodingSession = {
      ...mockSession,
      session_id: "cses_222",
      title: "2つ目のセッション",
    };
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession, secondSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : mockSession,
      effective_tool_ids: [],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    }));
    vi.mocked(codingApi.startCodingRun).mockResolvedValue({
      run: mockCodingRun({ run_id: "crun_nc", session_id: "cses_111" }),
    });
    let capturedSignal: AbortSignal | null = null;
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation((_runId, opts) => {
      capturedSignal = (opts as { signal?: AbortSignal }).signal ?? null;
      return new Promise(() => {});
    });
    vi.mocked(codingApi.cancelCodingRun).mockResolvedValue({ status: "cancel_signalled", run_id: "crun_nc" });

    const { unmount } = renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "キャンセルしない送信" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(capturedSignal).not.toBeNull());

    // Session switch aborts subscription but never calls cancel API.
    fireEvent.click(screen.getByText("2つ目のセッション"));
    await waitFor(() => expect(capturedSignal?.aborted).toBe(true));
    expect(codingApi.cancelCodingRun).not.toHaveBeenCalled();

    unmount();
    expect(codingApi.cancelCodingRun).not.toHaveBeenCalled();
  });

  it("resubscribes with cached Last-Event-ID and saves progress to sessionStorage", async () => {
    sessionStorage.setItem("run-sse:coding:crun_active:last-event-id", "3");
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: [],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: mockCodingRun({ run_id: "crun_active", session_id: "cses_111", status: "running" }),
      latest_run: null,
      orchestrator_tool_calls: [],
    });
    let seenLastEventId: number | null = null;
    let capturedOnEnvelope: ((e: Envelope) => void) | null = null;
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(async (_runId, opts) => {
      seenLastEventId = (opts as { lastEventId: number }).lastEventId;
      capturedOnEnvelope = (opts as { onEnvelope: (e: Envelope) => void }).onEnvelope;
      capturedOnEnvelope({
        eventId: 4,
        data: {
          event: "orchestrator_message",
          phase: "initial",
          message: {
            message_id: "cmsg_restored",
            session_id: "cses_111",
            sequence: 3,
            role: "orchestrator",
            content: "復元された判断",
            created_at: "2026-01-01T00:02:00Z",
          },
        },
      });
      // Keep the live subscription open so the restore finally-block does not
      // reload detail and wipe the folded message.
      await new Promise(() => {});
    });

    renderPage();

    await waitFor(() => expect(seenLastEventId).toBe(3));
    expect(await screen.findByText("復元された判断")).toBeInTheDocument();
    expect(sessionStorage.getItem("run-sse:coding:crun_active:last-event-id")).toBe("4");
  });

  it("ignores duplicate eventId (at-least-once redelivery)", async () => {
    let capturedOnEnvelope: ((e: Envelope) => void) | null = null;
    vi.mocked(codingApi.startCodingRun).mockResolvedValue({
      run: mockCodingRun({ run_id: "crun_dup", session_id: "cses_111" }),
    });
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation((_runId, opts) => {
      capturedOnEnvelope = (opts as { onEnvelope: (e: Envelope) => void }).onEnvelope;
      return new Promise(() => {});
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("Test App")).toBeInTheDocument());
    const textarea = screen.getByPlaceholderText(
      "指示・質問を入力…（Enterで送信 / Shift+Enterで改行）",
    );
    fireEvent.change(textarea, { target: { value: "重複テスト" } });
    fireEvent.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(capturedOnEnvelope).not.toBeNull());

    const msg = {
      message_id: "cmsg_dup",
      session_id: "cses_111",
      sequence: 10,
      role: "orchestrator" as const,
      content: "重複しない本文",
      created_at: "2026-01-01T00:02:00Z",
    };
    act(() => {
      capturedOnEnvelope?.({ eventId: 1, data: { event: "orchestrator_message", phase: "initial", message: msg } });
      capturedOnEnvelope?.({ eventId: 1, data: { event: "orchestrator_message", phase: "initial", message: msg } });
    });
    expect(screen.getAllByText("重複しない本文")).toHaveLength(1);
  });

  it("restores an active run on reload by folding replayed events", async () => {
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: [],
      has_custom_tools: false,
      available_tools: [],
      messages: [
        {
          message_id: "cmsg_1",
          session_id: "cses_111",
          sequence: 1,
          role: "user",
          content: "再読込前の依頼",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      active_run: mockCodingRun({ run_id: "crun_reload", session_id: "cses_111", status: "running" }),
      latest_run: null,
      orchestrator_tool_calls: [],
    });
    vi.mocked(codingApi.subscribeCodingRunEvents).mockImplementation(async (_runId, opts) => {
      const onEnvelope = (opts as { onEnvelope: (e: Envelope) => void }).onEnvelope;
      onEnvelope({
        eventId: 1,
        data: {
          event: "orchestrator_tool_call_detected",
          call_key: "1:1:0",
          tool_name: "web_search",
          phase: "initial",
          phase_turn: 1,
          iteration: 1,
          call_index: 0,
        },
      });
      onEnvelope({ eventId: 2, data: { event: "worker_start", attempt: 1, backend: "codex", prompt: "p" } });
      onEnvelope({
        eventId: 3,
        data: {
          event: "orchestrator_message",
          phase: "initial",
          message: {
            message_id: "cmsg_reload_orch",
            session_id: "cses_111",
            sequence: 2,
            role: "orchestrator",
            content: "リロード復元の判断",
            created_at: "2026-01-01T00:01:00Z",
          },
        },
      });
      // Keep the live subscription open so the restore finally-block does not
      // reload detail and wipe the folded state.
      await new Promise(() => {});
    });

    renderPage();

    expect(await screen.findByText("リロード復元の判断")).toBeInTheDocument();
    expect(codingApi.subscribeCodingRunEvents).toHaveBeenCalledWith(
      "crun_reload",
      expect.objectContaining({ lastEventId: 0 }),
    );
  });

  it("selects the session from ?session_id= when it belongs to listed sessions", async () => {
    const secondSession: codingApi.CodingSession = {
      ...mockSession,
      session_id: "cses_222",
      title: "2つ目のセッション",
    };
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession, secondSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockImplementation(async (sessionId: string) => ({
      session: sessionId === secondSession.session_id ? secondSession : mockSession,
      effective_tool_ids: [],
      has_custom_tools: false,
      available_tools: [],
      messages: [
        {
          message_id: `msg_${sessionId}`,
          session_id: sessionId,
          sequence: 1,
          role: "user",
          content: sessionId === secondSession.session_id ? "Bの本文" : "Aの本文",
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      active_run: null,
      latest_run: null,
      orchestrator_tool_calls: [],
    }));

    renderPage(["/coding?session_id=cses_222"]);

    await waitFor(() => {
      expect(codingApi.getCodingSessionDetail).toHaveBeenCalledWith("cses_222");
    });
    expect(await screen.findByText("Bの本文")).toBeInTheDocument();
  });

  it("falls back to the first session when ?session_id= does not belong to listed sessions", async () => {
    renderPage(["/coding?session_id=cses_missing"]);

    await waitFor(() => {
      expect(codingApi.getCodingSessionDetail).toHaveBeenCalledWith("cses_111");
    });
    expect(await screen.findByText("こんにちは！何かお手伝いしましょうか？")).toBeInTheDocument();
  });

  it("renders WaitingRunQuestionCard when latest_run is waiting_user and allows answering", async () => {
    const waitingRun = mockCodingRun({
      run_id: "crun_waiting",
      status: "waiting_user",
      hitl_run_id: "hitl_ask_123",
    });
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: waitingRun,
      orchestrator_tool_calls: [],
    });
    vi.mocked(clientApi.getHitlRun)
      .mockResolvedValueOnce({
        run_id: "hitl_ask_123",
        status: "pending_user",
        questions: [
          {
            question_key: "q1",
            display_text: "確認質問1",
            choices: [
              { value: "opt1", label: "選択肢1" },
              { value: "opt2", label: "選択肢2" },
            ],
            is_required: 1,
          },
        ],
      } as any)
      .mockResolvedValue({
        run_id: "hitl_ask_123",
        status: "completed",
        questions: [],
      } as any);
    vi.mocked(clientApi.submitHitlAnswer).mockResolvedValue({} as any);

    renderPage();

    await waitFor(() => {
      expect(clientApi.getHitlRun).toHaveBeenCalledWith("hitl_ask_123");
      expect(screen.getByText("確認質問1")).toBeInTheDocument();
      expect(screen.getByText("選択肢1")).toBeInTheDocument();
    });

    const radio = screen.getByLabelText("選択肢1");
    fireEvent.click(radio);

    const submitBtn = screen.getByRole("button", { name: "回答を送信" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(clientApi.submitHitlAnswer).toHaveBeenCalledWith(
        "hitl_ask_123",
        "q1",
        "opt1",
        undefined,
      );
    });
  });

  it("submits free-text via other choice and supports cancel", async () => {
    const waitingRun = mockCodingRun({
      run_id: "crun_waiting_other",
      status: "waiting_user",
      hitl_run_id: "hitl_ask_other",
    });
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: waitingRun,
      orchestrator_tool_calls: [],
    });
    vi.mocked(clientApi.getHitlRun)
      .mockResolvedValueOnce({
        run_id: "hitl_ask_other",
        status: "pending_user",
        questions: [
          {
            question_key: "q1",
            display_text: "確認質問other",
            choices: [
              { value: "opt1", label: "選択肢1" },
              { value: "other", label: "その他（自由入力）" },
            ],
            is_required: 1,
          },
        ],
      } as any)
      .mockResolvedValue({
        run_id: "hitl_ask_other",
        status: "completed",
        questions: [],
      } as any);
    vi.mocked(clientApi.submitHitlAnswer).mockResolvedValue({} as any);
    vi.mocked(clientApi.cancelHitlRun).mockResolvedValue({} as any);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("確認質問other")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByLabelText("その他（自由入力）"));
    fireEvent.click(screen.getByRole("button", { name: "回答を送信" }));
    // other without text is rejected client-side.
    expect(await screen.findByText("「その他」を選択した場合はテキストを入力してください。")).toBeInTheDocument();
    expect(clientApi.submitHitlAnswer).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("具体的な内容を入力してください（必須）"), {
      target: { value: "カスタム希望" },
    });
    fireEvent.click(screen.getByRole("button", { name: "回答を送信" }));
    await waitFor(() => {
      expect(clientApi.submitHitlAnswer).toHaveBeenCalledWith(
        "hitl_ask_other",
        "q1",
        "other",
        "カスタム希望",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      expect(clientApi.cancelHitlRun).toHaveBeenCalledWith("hitl_ask_other");
    });
  });

  it("shows resume-pending panel instead of an empty card when no questions are pending", async () => {
    const waitingRun = mockCodingRun({
      run_id: "crun_waiting_done",
      status: "waiting_user",
      hitl_run_id: "hitl_ask_done",
    });
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: waitingRun,
      orchestrator_tool_calls: [],
    });
    vi.mocked(clientApi.getHitlRun).mockResolvedValue({
      run_id: "hitl_ask_done",
      status: "ready_to_resume",
      questions: [
        {
          question_key: "q1",
          display_text: "回答済み質問",
          status: "answered",
          choices: [{ value: "opt1", label: "選択肢1" }],
          is_required: 1,
        },
      ],
    } as any);
    vi.mocked(clientApi.cancelHitlRun).mockResolvedValue({} as any);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/回答送信済み・再開待ち/)).toBeInTheDocument();
    });
    // No empty question frame: submit button must not exist.
    expect(screen.queryByRole("button", { name: "回答を送信" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      expect(clientApi.cancelHitlRun).toHaveBeenCalledWith("hitl_ask_done");
    });
  });

  it("shows failure notice with recovery cancel when the HITL run failed", async () => {
    const waitingRun = mockCodingRun({
      run_id: "crun_waiting_failed",
      status: "waiting_user",
      hitl_run_id: "hitl_ask_failed",
    });
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
      effective_tool_ids: ["web_search"],
      has_custom_tools: false,
      available_tools: [],
      messages: [],
      active_run: null,
      latest_run: waitingRun,
      orchestrator_tool_calls: [],
    });
    vi.mocked(clientApi.getHitlRun).mockResolvedValue({
      run_id: "hitl_ask_failed",
      status: "failed",
      error_message: "Handler 'coding.ask_user' is not registered.",
      questions: [
        {
          question_key: "q1",
          display_text: "回答済み質問",
          status: "answered",
          choices: [{ value: "opt1", label: "選択肢1" }],
          is_required: 1,
        },
      ],
    } as any);
    vi.mocked(clientApi.cancelHitlRun).mockResolvedValue({} as any);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/確認処理に失敗しました/)).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "回答を送信" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => {
      expect(clientApi.cancelHitlRun).toHaveBeenCalledWith("hitl_ask_failed");
    });
  });
});
