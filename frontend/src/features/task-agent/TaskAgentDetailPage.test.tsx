import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  approveTaskAgentTask,
  cancelHitlRun,
  cancelTaskAgentTask,
  getHitlRun,
  getTaskAgentTask,
  rejectTaskAgentTask,
  replanTaskAgentTask,
  submitHitlAnswer,
} from "../../api/client";
import TaskAgentDetailPage from "./TaskAgentDetailPage";

vi.mock("../../api/client", () => ({
  approveTaskAgentTask: vi.fn(),
  cancelHitlRun: vi.fn(),
  cancelTaskAgentTask: vi.fn(),
  getHitlRun: vi.fn(),
  getTaskAgentTask: vi.fn(),
  rejectTaskAgentTask: vi.fn(),
  replanTaskAgentTask: vi.fn(),
  submitHitlAnswer: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockGetTask = vi.mocked(getTaskAgentTask);
const mockApprove = vi.mocked(approveTaskAgentTask);
const mockReject = vi.mocked(rejectTaskAgentTask);
const mockCancel = vi.mocked(cancelTaskAgentTask);
const mockReplan = vi.mocked(replanTaskAgentTask);
const mockGetHitlRun = vi.mocked(getHitlRun);
const mockSubmitHitlAnswer = vi.mocked(submitHitlAnswer);

function baseDetail(overrides: Record<string, any> = {}) {
  return {
    task: {
      task_id: "task_aaa",
      prompt_text: "今日の予定をまとめて",
      status: "waiting_approval",
      current_plan_id: "tplan_1",
      worker_instance_id: "w1",
      active_child_kind: null,
      active_child_run_id: null,
      result_summary: null,
      error_summary: null,
      created_at: "2026-09-14T10:00:00+09:00",
      updated_at: "2026-09-14T10:00:00+09:00",
      started_at: "2026-09-14T10:01:00+09:00",
      finished_at: null,
      ...overrides,
    },
    plans: [
      {
        plan_id: "tplan_1",
        task_id: "task_aaa",
        version: 1,
        plan: { purpose: "まとめる", steps: [], completion_criteria: "done" },
        approval_policy_snapshot: { calendar_read: "auto" },
        status: "pending",
        rejection_reason: null,
        created_at: "2026-09-14T10:01:00+09:00",
        decided_at: null,
      },
    ],
    events: [],
  };
}

function renderPage(taskId = "task_aaa") {
  return render(
    <MemoryRouter initialEntries={[`/task-agent/${taskId}`]}>
      <Routes>
        <Route path="/task-agent" element={<div>list</div>} />
        <Route path="/task-agent/:taskId" element={<TaskAgentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetTask.mockResolvedValue(baseDetail() as any);
  mockGetHitlRun.mockRejectedValue(new Error("no hitl"));
  mockApprove.mockResolvedValue({} as any);
  mockReject.mockResolvedValue({} as any);
  mockCancel.mockResolvedValue({} as any);
  mockReplan.mockResolvedValue({} as any);
  mockSubmitHitlAnswer.mockResolvedValue({ success: true });
});

describe("TaskAgentDetailPage", () => {
  it("shows approve/reject for waiting_approval and calls approve", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("今日の予定をまとめて");
    const approve = screen.getByTestId("task-approve");
    const reject = screen.getByTestId("task-reject");
    expect(reject).toBeDisabled();
    await user.click(approve);
    await waitFor(() => expect(mockApprove).toHaveBeenCalledWith("task_aaa"));
  });

  it("reject requires a reason", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("今日の予定をまとめて");
    await user.type(screen.getByLabelText("差戻し理由"), "根拠が不足");
    const reject = screen.getByTestId("task-reject");
    expect(reject).not.toBeDisabled();
    await user.click(reject);
    await waitFor(() =>
      expect(mockReject).toHaveBeenCalledWith("task_aaa", "根拠が不足"),
    );
  });

  it("shows replan only for interrupted", async () => {
    mockGetTask.mockResolvedValue(baseDetail({ status: "interrupted" }) as any);
    renderPage();
    await screen.findByTestId("task-replan");
    expect(screen.queryByTestId("task-approve")).not.toBeInTheDocument();
  });

  it("cancel calls the cancel API", async () => {
    const user = userEvent.setup();
    mockGetTask.mockResolvedValue(baseDetail({ status: "running" }) as any);
    renderPage();
    await screen.findByTestId("task-cancel");
    await user.click(screen.getByTestId("task-cancel"));
    await waitFor(() => expect(mockCancel).toHaveBeenCalledWith("task_aaa"));
  });

  it("renders a directional plan with approval scope", async () => {
    mockGetTask.mockResolvedValue({
      ...baseDetail(),
      plans: [
        {
          plan_id: "tplan_2",
          task_id: "task_aaa",
          version: 2,
          plan: {
            plan_version: 2,
            purpose: "好みを記憶する",
            strategy: "検索して提案",
            capabilities: [
              { capability_key: "vault_search", intent: "検索する" },
              { capability_key: "memory_propose", intent: "提案する" },
            ],
            allowed_agent_ids: ["agent_1"],
            allowed_project_ids: [3],
            constraints: "推測禁止",
            completion_criteria: "候補作成",
            max_actions: 8,
          },
          approval_policy_snapshot: { vault_search: "auto" },
          status: "pending",
          rejection_reason: null,
          created_at: "2026-09-14T10:01:00+09:00",
          decided_at: null,
        },
      ],
      events: [
        {
          event_id: 9,
          task_id: "task_aaa",
          seq: 2,
          event_type: "capability_completed",
          payload: {
            action_index: 0,
            capability_key: "vault_search",
            inputs: { query: "好み" },
            summary: "obs",
            observation: "obs",
          },
          created_at: "2026-09-14T10:02:00+09:00",
        },
      ],
    } as any);
    renderPage();
    await screen.findByText("好みを記憶する");
    expect(
      screen.getByText(/承認対象は方向性とCapability範囲です/),
    ).toBeInTheDocument();
    expect(screen.getByText("vault_search")).toBeInTheDocument();
    expect(screen.getByText(/委譲可能なAgent: agent_1/)).toBeInTheDocument();
    expect(screen.getByText(/実行可能なProject: 3/)).toBeInTheDocument();
    expect(screen.getByText("最大Action数: 8")).toBeInTheDocument();
    expect(screen.getByText(/実行Action履歴/)).toBeInTheDocument();
  });

  it("keeps rendering legacy static plans", async () => {
    renderPage();
    await screen.findByText("まとめる");
    expect(screen.getByText(/旧形式の静的Plan/)).toBeInTheDocument();
  });

  it("embeds the HITL question card and submits the answer", async () => {
    const user = userEvent.setup();
    mockGetTask.mockResolvedValue({
      ...baseDetail({ status: "waiting_user" }),
      events: [
        {
          event_id: 1,
          task_id: "task_aaa",
          seq: 1,
          event_type: "hitl_question_asked",
          payload: { hitl_run_id: "tasks_task_aaa_1", question_set_id: "target" },
          created_at: "2026-09-14T10:02:00+09:00",
        },
      ],
    } as any);
    mockGetHitlRun.mockResolvedValue({
      run_id: "tasks_task_aaa_1",
      status: "pending_user",
      questions: [
        {
          question_id: "q1",
          question_key: "target",
          status: "pending",
          question_type: "select",
          display_text: "どのプロジェクトですか?",
          choices: [
            { value: "a", label: "A" },
            { value: "b", label: "B" },
          ],
        },
      ],
    } as any);
    renderPage();
    await screen.findByText("どのプロジェクトですか?");
    expect(mockGetHitlRun).toHaveBeenCalledWith("tasks_task_aaa_1");
    const radios = await screen.findAllByRole("radio");
    await user.click(radios[0]);
    const submit = screen.getByRole("button", { name: /回答|送信|決定/ });
    await user.click(submit);
    await waitFor(() =>
      expect(mockSubmitHitlAnswer).toHaveBeenCalledWith(
        "tasks_task_aaa_1",
        "target",
        expect.anything(),
        undefined,
      ),
    );
  });
});
