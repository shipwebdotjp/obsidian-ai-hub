import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import JobStatePage from "./JobStatePage";

vi.mock("../../api/client", () => ({
  apiGet: vi.fn(),
  listJobStates: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { listJobStates } from "../../api/client";

const mockListJobStates = vi.mocked(listJobStates);

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders job state cards with aggregated status and health labels", async () => {
  mockListJobStates.mockResolvedValueOnce({
    items: [
      {
        job_id: "merge_inbox",
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

  render(<JobStatePage />);

  await waitFor(() => {
    expect(screen.getByText("merge_inbox")).toBeInTheDocument();
  });

  expect(screen.getByText("ジョブ状態")).toBeInTheDocument();
  expect(
    screen.getByText("定期・高頻度ジョブの動作状態を確認できます（空振りはログに出さずここに集計）")
  ).toBeInTheDocument();
  expect(screen.getByText("稼働中")).toBeInTheDocument();
  expect(screen.getByText("3 回")).toBeInTheDocument();
  expect(screen.getByText("5 / 2 / 0")).toBeInTheDocument();
});

it("displays error warning when job-state API fails", async () => {
  mockListJobStates.mockRejectedValueOnce(new Error("fetch failed"));

  render(<JobStatePage />);

  await waitFor(() => {
    expect(screen.getByText("ジョブ状態を取得できません")).toBeInTheDocument();
  });
});

it("polls job-states every 30 seconds", async () => {
  vi.useFakeTimers();
  mockListJobStates.mockResolvedValue({ items: [] });

  render(<JobStatePage />);

  expect(mockListJobStates).toHaveBeenCalledTimes(1);

  await act(async () => {
    vi.advanceTimersByTime(30_000);
  });
  expect(mockListJobStates).toHaveBeenCalledTimes(2);

  vi.useRealTimers();
});
