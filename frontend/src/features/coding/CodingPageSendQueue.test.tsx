import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CodingPage from "./CodingPage";
import * as codingApi from "../../api/coding";
import {
  createQueuedCodingMessage,
  writeCodingSendQueue,
} from "./utils/codingSendQueue";
import type { CodingRun, CodingSessionDetail } from "../../api/coding";

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
  updateCodingSessionModel: vi.fn(),
  getSlashCandidates: vi.fn(),
}));

import { getHitlRun, cancelHitlRun } from "../../api/client";

const mockGetDetail = vi.mocked(codingApi.getCodingSessionDetail);
const mockStart = vi.mocked(codingApi.startCodingRun);
const mockSubscribe = vi.mocked(codingApi.subscribeCodingRunEvents);

const projectItem: codingApi.CodingProjectItem = {
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

const session: codingApi.CodingSession = {
  session_id: "cses_111",
  project_id: 1,
  backend: "opencode",
  repo_path: "/app/test_repo",
  external_session_id: null,
  title: "新規セッション",
  transport: "acp",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function run(runId: string, status: CodingRun["status"] = "queued"): CodingRun {
  return {
    run_id: runId,
    session_id: session.session_id,
    user_message_id: `u_${runId}`,
    orchestrator_message_id: null,
    worker_message_id: null,
    status,
    hitl_run_id: null,
    dirty_tree_at_start: null,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
  };
}

function detail(overrides: Partial<CodingSessionDetail> = {}): CodingSessionDetail {
  return {
    session,
    effective_tool_ids: [],
    has_custom_tools: false,
    available_tools: [],
    messages: [],
    active_run: null,
    latest_run: null,
    runs: [],
    orchestrator_tool_calls: [],
    ...overrides,
  };
}

function doneEnvelope(runId: string) {
  return {
    eventId: 1,
    data: { event: "done", run_id: runId, status: "completed" },
  };
}

const PLACEHOLDER = /指示・質問を入力/;

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  vi.mocked(codingApi.listCodingProjects).mockResolvedValue([projectItem]);
  vi.mocked(codingApi.listCodingSessions).mockResolvedValue([session]);
  vi.mocked(codingApi.getGitStatus).mockResolvedValue(null as never);
  vi.mocked(codingApi.getCodingConfig).mockResolvedValue({
    default_backend: "opencode",
    opencode_model: null,
    available_models: [],
  });
  vi.mocked(codingApi.getSlashCandidates).mockResolvedValue({
    candidates: [],
    has_skills_tool: true,
  });
  mockGetDetail.mockResolvedValue(detail());
  mockSubscribe.mockImplementation(async () => {});
  vi.mocked(cancelHitlRun).mockResolvedValue({ success: true });
});

describe("CodingPage send queue", () => {
  it("queues messages while streaming and sends them in order after the turn ends", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_runId, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart
      .mockResolvedValueOnce({ run: run("crun_1") })
      .mockResolvedValueOnce({ run: run("crun_2") });

    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(PLACEHOLDER);
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "second");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await screen.findByTestId("coding-queued-messages");
    expect(screen.getByText("待機 1件")).toBeInTheDocument();
    expect(mockStart).toHaveBeenCalledTimes(1);

    emitters[0](doneEnvelope("crun_1"));

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(2));
    expect(mockStart.mock.calls[1][1]).toBe("second");
    await waitFor(() =>
      expect(screen.queryByTestId("coding-queued-messages")).not.toBeInTheDocument(),
    );
  });

  it("keeps an in-progress composer draft when the previous turn completes", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_runId, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart.mockResolvedValueOnce({ run: run("crun_1") });

    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );
    const input = (await screen.findByPlaceholderText(PLACEHOLDER)) as HTMLTextAreaElement;
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "draft in progress");
    emitters[0](doneEnvelope("crun_1"));

    await waitFor(() => expect(input.value).toBe("draft in progress"));
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("removes a queued message without sending it", async () => {
    const user = userEvent.setup();
    const emitters: Array<(e: unknown) => void> = [];
    mockSubscribe.mockImplementation(async (_runId, opts) => {
      emitters.push((opts as { onEnvelope: (e: unknown) => void }).onEnvelope);
      await new Promise<void>(() => {});
    });
    mockStart.mockResolvedValueOnce({ run: run("crun_1") });

    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );
    const input = await screen.findByPlaceholderText(PLACEHOLDER);
    await user.type(input, "first");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));

    await user.type(input, "drop me");
    await user.click(screen.getByRole("button", { name: "送信" }));
    await screen.findByTestId("coding-queued-messages");
    await user.click(screen.getByRole("button", { name: "送信待ちメッセージを削除" }));
    await waitFor(() =>
      expect(screen.queryByTestId("coding-queued-messages")).not.toBeInTheDocument(),
    );

    emitters[0](doneEnvelope("crun_1"));
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(mockStart).toHaveBeenCalledTimes(1);
  });

  it("restores a persisted queue on load and sends when the session is idle", async () => {
    writeCodingSendQueue(session.session_id, [
      createQueuedCodingMessage({ content: "restored message" }),
    ]);
    mockStart.mockResolvedValueOnce({ run: run("crun_restored") });

    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    expect(mockStart.mock.calls[0][1]).toBe("restored message");
  });

  it("keeps the queued item pending on 409 instead of erroring or looping", async () => {
    writeCodingSendQueue(session.session_id, [
      createQueuedCodingMessage({ content: "blocked message" }),
    ]);
    let activeRunVisible = false;
    mockGetDetail.mockImplementation(async () =>
      detail({
        runs: activeRunVisible ? [run("crun_other", "running")] : [],
        active_run: activeRunVisible ? run("crun_other", "running") : null,
      }),
    );
    mockStart.mockImplementation(async () => {
      activeRunVisible = true;
      throw Object.assign(new Error("active run"), { status: 409 });
    });
    mockSubscribe.mockImplementation(async () => {
      await new Promise<void>(() => {});
    });

    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(screen.getByText("blocked message")).toBeInTheDocument();
    expect(screen.queryByTestId("coding-queued-error")).not.toBeInTheDocument();
  });

  it("holds the queue while a question is pending and sends after it is resolved", async () => {
    const waitingRun = { ...run("crun_waiting", "waiting_user"), hitl_run_id: "hitl_1" };
    mockGetDetail.mockImplementation(async () =>
      detail({ latest_run: waitingRun, runs: [waitingRun] }),
    );
    vi.mocked(getHitlRun).mockResolvedValue({
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
    writeCodingSendQueue(session.session_id, [
      createQueuedCodingMessage({ content: "after answer" }),
    ]);
    mockStart.mockResolvedValueOnce({ run: run("crun_after") });

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <CodingPage />
      </MemoryRouter>,
    );

    await screen.findByText("Continue?");
    expect(mockStart).not.toHaveBeenCalled();

    mockGetDetail.mockResolvedValue(detail());
    await user.click(screen.getByRole("button", { name: "取消" }));
    await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(1));
    expect(mockStart.mock.calls[0][1]).toBe("after answer");
  });
});
