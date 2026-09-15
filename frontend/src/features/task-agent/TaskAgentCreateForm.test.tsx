import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, createTaskAgentTask } from "../../api/client";
import TaskAgentCreateForm from "./TaskAgentCreateForm";

vi.mock("../../api/client", () => ({
  createTaskAgentTask: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

const mockCreate = vi.mocked(createTaskAgentTask);

const createdTask = {
  task_id: "task_new1",
  prompt_text: "調べてまとめて",
  status: "queued",
  current_plan_id: null,
  worker_instance_id: null,
  active_child_kind: null,
  active_child_run_id: null,
  result_summary: null,
  error_summary: null,
  created_at: "2026-09-14T10:00:00+09:00",
  updated_at: "2026-09-14T10:00:00+09:00",
  started_at: null,
  finished_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TaskAgentCreateForm", () => {
  it("空入力では投入ボタンが無効で送信されない", async () => {
    const user = userEvent.setup();
    const onCreated = vi.fn();
    render(<TaskAgentCreateForm onCreated={onCreated} onCancel={() => {}} />);

    expect(
      screen.getByRole("button", { name: "投入する" }),
    ).toBeDisabled();

    // 空白のみでも無効のまま。
    await user.type(screen.getByLabelText("新規タスクの依頼内容"), "   ");
    expect(
      screen.getByRole("button", { name: "投入する" }),
    ).toBeDisabled();

    expect(mockCreate).not.toHaveBeenCalled();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("成功時はonCreatedに作成Taskを渡す", async () => {
    const user = userEvent.setup();
    mockCreate.mockResolvedValue(createdTask);
    const onCreated = vi.fn();
    render(<TaskAgentCreateForm onCreated={onCreated} onCancel={() => {}} />);

    await user.type(
      screen.getByLabelText("新規タスクの依頼内容"),
      "調べてまとめて",
    );
    await user.click(screen.getByRole("button", { name: "投入する" }));

    await waitFor(() =>
      expect(mockCreate).toHaveBeenCalledWith({
        prompt_text: "調べてまとめて",
      }),
    );
    expect(onCreated).toHaveBeenCalledWith(createdTask);
  });

  it("API失敗時はエラーを表示する", async () => {
    const user = userEvent.setup();
    // モックの ApiError は (status, message) 形式のため message を付け直す。
    const apiError = new ApiError(500, "投入に失敗しました");
    apiError.message = "投入に失敗しました";
    mockCreate.mockRejectedValue(apiError);
    const onCreated = vi.fn();
    render(<TaskAgentCreateForm onCreated={onCreated} onCancel={() => {}} />);

    await user.type(screen.getByLabelText("新規タスクの依頼内容"), "何か");
    await user.click(screen.getByRole("button", { name: "投入する" }));

    expect(await screen.findByText("投入に失敗しました")).toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("キャンセルでonCancelを呼ぶ", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<TaskAgentCreateForm onCreated={() => {}} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: "キャンセル" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
