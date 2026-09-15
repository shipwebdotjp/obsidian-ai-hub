import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelTaskAgentTask,
  getTaskAgentTask,
  listTaskAgentTasks,
} from "../../api/client";
import TaskAgentListPage from "./TaskAgentListPage";

vi.mock("../../api/client", () => ({
  listTaskAgentTasks: vi.fn(),
  getTaskAgentTask: vi.fn(),
  cancelTaskAgentTask: vi.fn(),
  createTaskAgentTask: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockListTaskAgentTasks = vi.mocked(listTaskAgentTasks);

const sampleTasks = [
  {
    task_id: "task_aaa",
    prompt_text: "今日の予定をまとめて",
    status: "waiting_approval",
    current_plan_id: "tplan_1",
    worker_instance_id: null,
    active_child_kind: null,
    active_child_run_id: null,
    result_summary: null,
    error_summary: null,
    created_at: "2026-09-14T10:00:00+09:00",
    updated_at: "2026-09-14T10:00:00+09:00",
    started_at: null,
    finished_at: null,
  },
  {
    task_id: "task_bbb",
    prompt_text: "Webで調べて",
    status: "completed",
    current_plan_id: "tplan_2",
    worker_instance_id: "w1",
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

function renderPage(initialPath = "/task-agent") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/task-agent" element={<TaskAgentListPage />} />
        <Route
          path="/task-agent/capabilities"
          element={<div data-testid="capabilities-marker">capabilities</div>}
        />
        <Route
          path="/task-agent/:taskId"
          element={<div data-testid="detail-marker">detail</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockListTaskAgentTasks.mockImplementation(async (params) => ({
    items: params.status
      ? sampleTasks.filter((t) => t.status === params.status)
      : sampleTasks,
    total: params.status
      ? sampleTasks.filter((t) => t.status === params.status).length
      : 2,
  }) as any);
});

describe("TaskAgentListPage", () => {
  it("fetches and lists tasks with status badges", async () => {
    renderPage();
    await waitFor(() =>
      expect(mockListTaskAgentTasks).toHaveBeenCalledWith({ limit: 100 }),
    );
    expect(await screen.findByText("今日の予定をまとめて")).toBeInTheDocument();
    const rows = screen.getAllByTestId("task-agent-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0] as HTMLElement).getByText("承認待ち")).toBeInTheDocument();
    expect(within(rows[1] as HTMLElement).getByText("完了")).toBeInTheDocument();
  });

  it("filters by status via the server param", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("今日の予定をまとめて");
    const select = screen.getByLabelText("ステータスフィルター");
    await user.selectOptions(select, "queued");
    await waitFor(() =>
      expect(mockListTaskAgentTasks).toHaveBeenCalledWith({
        status: "queued",
        limit: 100,
      }),
    );
    expect(screen.queryByTestId("task-agent-row")).not.toBeInTheDocument();
    await user.selectOptions(select, "completed");
    const rows2 = await screen.findAllByTestId("task-agent-row");
    expect(rows2).toHaveLength(1);
    expect(
      within(rows2[0] as HTMLElement).getByText("Webで調べて"),
    ).toBeInTheDocument();
  });

  it("navigates to detail on row click", async () => {
    const user = userEvent.setup();
    renderPage();
    const rows = await screen.findAllByTestId("task-agent-row");
    await user.click(rows[0]);
    expect(await screen.findByTestId("detail-marker")).toBeInTheDocument();
  });

  it("shows a settings gear link to the existing capabilities URL", async () => {
    renderPage();
    await screen.findByText("今日の予定をまとめて");
    const link = screen.getByRole("link", { name: "Task Capability設定を開く" });
    expect(link).toHaveAttribute("href", "/task-agent/capabilities");
    expect(link).toHaveAttribute("title", "Task Capability設定を開く");
  });

  it("navigates to the capabilities page on gear click", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("今日の予定をまとめて");
    await user.click(
      screen.getByRole("link", { name: "Task Capability設定を開く" }),
    );
    expect(await screen.findByTestId("capabilities-marker")).toBeInTheDocument();
  });
});
