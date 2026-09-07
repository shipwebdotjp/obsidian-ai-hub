import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import TaskStatePage from "./TaskStatePage";

vi.mock("../../api/client", () => ({
  apiGet: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { apiGet } from "../../api/client";

const mockApiGet = vi.mocked(apiGet);

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders task state cards with aggregated status and health labels", async () => {
  mockApiGet.mockResolvedValueOnce({
    items: [
      {
        task_id: "merge_inbox",
        last_check_at: new Date().toISOString(),
        consecutive_empty_count: 3,
        last_processed_at: new Date(Date.now() - 3600_000).toISOString(),
        last_error_at: null,
        last_error_message: null,
        last_error_type: null,
        processed_count: 5,
        skipped_count: 2,
        failed_count: 0,
        updated_at: new Date().toISOString(),
      },
    ],
  });

  render(<TaskStatePage />);

  await waitFor(() => {
    expect(screen.getByText("merge_inbox")).toBeInTheDocument();
  });

  expect(screen.getByText("タスク状態")).toBeInTheDocument();
  expect(
    screen.getByText("定期・高頻度タスクの動作状態を確認できます（空振りはログに出さずここに集計）")
  ).toBeInTheDocument();
  expect(screen.getByText("稼働中")).toBeInTheDocument();
  expect(screen.getByText("3 回")).toBeInTheDocument();
  expect(screen.getByText("5 / 2 / 0")).toBeInTheDocument();
});

it("displays error warning when task-state API fails", async () => {
  mockApiGet.mockRejectedValueOnce(new Error("fetch failed"));

  render(<TaskStatePage />);

  await waitFor(() => {
    expect(screen.getByText("タスク状態を取得できません")).toBeInTheDocument();
  });
});

it("polls task-states every 30 seconds", async () => {
  vi.useFakeTimers();
  mockApiGet.mockResolvedValue({ items: [] });

  render(<TaskStatePage />);

  expect(mockApiGet).toHaveBeenCalledTimes(1);

  await act(async () => {
    vi.advanceTimersByTime(30_000);
  });
  expect(mockApiGet).toHaveBeenCalledTimes(2);

  vi.useRealTimers();
});
