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
    vi.mocked(codingApi.listCodingProjects).mockResolvedValue([mockProjectItem]);
    vi.mocked(codingApi.listCodingSessions).mockResolvedValue([mockSession]);
    vi.mocked(codingApi.getCodingSessionDetail).mockResolvedValue({
      session: mockSession,
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

  it("opens new session modal and creates a session", async () => {
    vi.mocked(codingApi.createCodingSession).mockResolvedValue({
      ...mockSession,
      session_id: "cses_222",
      title: "新セッション2",
    });

    render(<CodingPage />);

    await waitFor(() => {
      expect(screen.getByText("Test App")).toBeInTheDocument();
    });

    const newBtn = screen.getByRole("button", { name: "+ 新規" });
    fireEvent.click(newBtn);

    expect(screen.getByText("新規コーディングセッション作成")).toBeInTheDocument();

    const titleInput = screen.getByPlaceholderText("例: リファクタリング作業");
    fireEvent.change(titleInput, { target: { value: "新セッション2" } });

    const submitBtn = screen.getByRole("button", { name: "作成" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(codingApi.createCodingSession).toHaveBeenCalledWith(1, "codex", "新セッション2");
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

    const textarea = screen.getByPlaceholderText("指示・質問を入力 (Cmd+Enterで送信)...");
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
});
