import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getHitlRun,
  getTaskAgentTask,
  listTaskAgentTasks,
} from "../../api/client";
import TaskAgentPage from "./TaskAgentPage";

vi.mock("../../api/client", () => ({
  approveTaskAgentTask: vi.fn(),
  cancelHitlRun: vi.fn(),
  cancelTaskAgentTask: vi.fn(),
  getHitlRun: vi.fn(),
  getTaskAgentTask: vi.fn(),
  listTaskAgentTasks: vi.fn(),
  rejectTaskAgentTask: vi.fn(),
  replanTaskAgentTask: vi.fn(),
  submitHitlAnswer: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockList = vi.mocked(listTaskAgentTasks);
const mockGetTask = vi.mocked(getTaskAgentTask);
const mockGetHitlRun = vi.mocked(getHitlRun);

const sampleTasks = [
  {
    task_id: "task_aaa",
    prompt_text: "今日の予定をまとめて",
    status: "running",
    current_plan_id: "tplan_1",
    worker_instance_id: "w1",
    active_child_kind: "agent",
    active_child_run_id: "arun_1",
    result_summary: null,
    error_summary: null,
    created_at: "2026-09-14T10:00:00+09:00",
    updated_at: "2026-09-14T10:00:00+09:00",
    started_at: "2026-09-14T10:01:00+09:00",
    finished_at: null,
  },
  {
    task_id: "task_bbb",
    prompt_text: "Webで調べて",
    status: "completed",
    current_plan_id: null,
    worker_instance_id: null,
    active_child_kind: null,
    active_child_run_id: null,
    result_summary: "done",
    error_summary: null,
    created_at: "2026-09-13T10:00:00+09:00",
    updated_at: "2026-09-13T10:00:00+09:00",
    started_at: "2026-09-13T10:01:00+09:00",
    finished_at: "2026-09-13T10:02:00+09:00",
  },
];

const detailAaa = {
  task: sampleTasks[0],
  plans: [
    {
      plan_id: "tplan_1",
      task_id: "task_aaa",
      version: 1,
      plan: { purpose: "まとめる", capabilities: [] },
      approval_policy_snapshot: { calendar_read: "auto" },
      status: "approved",
      rejection_reason: null,
      created_at: "2026-09-14T10:01:00+09:00",
      decided_at: "2026-09-14T10:02:00+09:00",
    },
  ],
  events: [
    {
      event_id: 1,
      task_id: "task_aaa",
      seq: 1,
      event_type: "child_run_started",
      payload: {
        step_index: 0,
        child_kind: "agent",
        child_run_id: "arun_1",
        session_id: "asess_1",
        agent_id: "agent_9",
      },
      created_at: "2026-09-14T10:02:00+09:00",
    },
    {
      event_id: 2,
      task_id: "task_aaa",
      seq: 2,
      event_type: "hitl_question_asked",
      payload: { hitl_run_id: "hrun_7", question_set_id: "target" },
      created_at: "2026-09-14T10:03:00+09:00",
    },
  ],
};

function renderPage(initialPath = "/task-agent") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/task-agent" element={<TaskAgentPage />} />
        <Route path="/task-agent/:taskId" element={<TaskAgentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockList.mockResolvedValue({ items: sampleTasks, total: 2 } as any);
  mockGetTask.mockResolvedValue(detailAaa as any);
  mockGetHitlRun.mockRejectedValue(new Error("no hitl"));
});

describe("TaskAgentPage (master-detail)", () => {
  it("shows the list with a placeholder when nothing is selected", async () => {
    renderPage("/task-agent");
    expect(await screen.findByText("今日の予定をまとめて")).toBeInTheDocument();
    expect(
      screen.getByText("一覧からTaskを選択してください。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Task詳細")).not.toBeInTheDocument();
  });

  it("shows list and detail side by side with selection state", async () => {
    const { container } = renderPage("/task-agent/task_aaa");
    // 一覧ペインと詳細ペインが同時に存在する。
    // （プロンプト文は一覧行と詳細のユーザータスクの双方に現れる）
    expect(
      await screen.findAllByText("今日の予定をまとめて"),
    ).not.toHaveLength(0);
    expect(screen.getByText("Task詳細")).toBeInTheDocument();
    const rows = screen.getAllByTestId("task-agent-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-selected", "true");
    expect(rows[1]).toHaveAttribute("data-selected", "false");
    expect(
      within(rows[0] as HTMLElement).getByText("今日の予定をまとめて"),
    ).toBeInTheDocument();
    // 生 JSON の直接表示（pre）は残っていない。
    expect(container.querySelector("pre")).toBeNull();
  });

  it("marks the selected row and links child runs to existing routes", async () => {
    renderPage("/task-agent/task_aaa");
    await screen.findByText("Task詳細");
    const childLinks = screen.getAllByTestId("child-run-link");
    expect(childLinks.length).toBeGreaterThanOrEqual(1);
    expect(childLinks[0]).toHaveAttribute(
      "href",
      "/agents?session_id=asess_1",
    );
    expect(childLinks[0]).toHaveTextContent("arun_1");
    const hitlLink = screen.getByTestId("hitl-run-link");
    expect(hitlLink).toHaveAttribute("href", "/hitl?run_id=hrun_7");
    // 承認ポリシースナップショット（従来は非表示だった情報）も欠落なく表示。
    expect(screen.getByText("承認ポリシースナップショット")).toBeInTheDocument();
    expect(screen.getByText("calendar_read")).toBeInTheDocument();
  });

  it("navigates back to the list via the mobile back link", async () => {
    const user = userEvent.setup();
    renderPage("/task-agent/task_aaa");
    await screen.findByText("Task詳細");
    await user.click(screen.getByRole("link", { name: "一覧に戻る" }));
    expect(
      await screen.findByText("一覧からTaskを選択してください。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Task詳細")).not.toBeInTheDocument();
  });

  it("navigates from a list row to the detail", async () => {
    const user = userEvent.setup();
    renderPage("/task-agent");
    const rows = await screen.findAllByTestId("task-agent-row");
    await user.click(rows[0]);
    expect(await screen.findByText("Task詳細")).toBeInTheDocument();
    expect(mockGetTask).toHaveBeenCalledWith("task_aaa");
  });
});
