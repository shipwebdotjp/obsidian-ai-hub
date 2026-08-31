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
});
