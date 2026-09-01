import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import PlannerPage from "./PlannerPage";

vi.mock("../../api/client", () => ({
  getPlannerTimeline: vi.fn(),
  updatePlannerProposal: vi.fn(),
  rejectPlannerProposal: vi.fn(),
  promotePlannerProposal: vi.fn(),
  generatePlannerProposals: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import {
  getPlannerTimeline,
  updatePlannerProposal,
  rejectPlannerProposal,
  promotePlannerProposal,
  generatePlannerProposals,
} from "../../api/client";

const mockGetTimeline = vi.mocked(getPlannerTimeline);
const mockUpdate = vi.mocked(updatePlannerProposal);
const mockReject = vi.mocked(rejectPlannerProposal);
const mockPromote = vi.mocked(promotePlannerProposal);
const mockGenerate = vi.mocked(generatePlannerProposals);

const sampleTimeline = {
  apple_events: [
    {
      title: "Appleミーティング",
      start_time: "2026-08-20T09:00:00",
      end_time: "2026-08-20T10:00:00",
      location: null,
      all_day: false,
      source: "apple",
    },
    { title: "終日予定", start_time: "2026-08-20T00:00:00", end_time: "2026-08-20T00:00:00", location: null, all_day: true, source: "apple" },
  ],
  apple_reminders: [{ title: "リマインダーA", due_date: "2026-08-20", source: "apple" }],
  apple_error: null,
  recurring_events: [{ title: "定期掃除", date: "2026-08-20", category: 1, source: "recurring" }],
  inbox_pending: [
    {
      run_id: "run-1",
      handler: "calendar.add_approved_event",
      title: "確認待ち予定",
      kind: "calendar",
      start_time: "2026-08-20T14:00:00",
      end_time: null,
      location: null,
      due_date: null,
    },
  ],
  ai_proposals: [
    {
      proposal_id: "pp-1",
      kind: "calendar",
      title: "歯科検診",
      rationale: "最近のノートに予約希望があったため",
      generation_source: "daily_06:00",
      status: "proposed",
      fingerprint: null,
      external_result: null,
      start_time: "2026-08-20T10:00:00",
      end_time: null,
      location: null,
      due_date: null,
      created_at: "2026-08-19T06:00:00Z",
      updated_at: "2026-08-19T06:00:00Z",
      expired_at: null,
      promoted_at: null,
      rejected_at: null,
    },
  ],
};

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-20T00:00:00"));
  vi.clearAllMocks();
  mockGetTimeline.mockResolvedValue(sampleTimeline as any);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("PlannerPage", () => {
  const getDates = () => {
    const now = new Date();
    const monthLabel = `${now.getFullYear()}/${now.getMonth() + 1}`;
    const prevMonth = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const prevMonthLabel = `${prevMonth.getFullYear()}/${prevMonth.getMonth() + 1}`;
    const fmt = (d: Date) =>
      `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(
        d.getDate(),
      ).padStart(2, "0")}`;
    const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dow = weekStart.getDay();
    weekStart.setDate(weekStart.getDate() + (dow === 0 ? -6 : 1 - dow));
    const weekEnd = new Date(weekStart);
    weekEnd.setDate(weekEnd.getDate() + 6);
    const weekLabel = `${fmt(weekStart)} 〜 ${fmt(weekEnd)}`;
    const prevWeekEnd = new Date(weekStart);
    prevWeekEnd.setDate(prevWeekEnd.getDate() - 1);
    const prevWeekStart = new Date(prevWeekEnd);
    prevWeekStart.setDate(prevWeekStart.getDate() - 6);
    const prevWeekLabel = `${fmt(prevWeekStart)} 〜 ${fmt(prevWeekEnd)}`;
    return { now, monthLabel, prevMonthLabel, weekLabel, prevWeekLabel };
  };

  it("loads the default month timeline and renders all layers", async () => {
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    const { monthLabel } = getDates();
    expect(screen.getByRole("button", { name: "月" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(monthLabel)).toBeInTheDocument();
    expect(screen.getByText("Appleミーティング")).toBeInTheDocument();
    expect(screen.getByText("◐ 終日予定")).toBeInTheDocument();
    expect(screen.getByText(/リマインダーA/)).toBeInTheDocument();
    expect(screen.getByText(/定期掃除/)).toBeInTheDocument();
    expect(screen.getByText(/確認待ち予定/)).toBeInTheDocument();
    expect(screen.getByText(/歯科検診/)).toBeInTheDocument();
  });

  it("renders all-day events across the inclusive end date", async () => {
    mockGetTimeline.mockResolvedValue({
      ...sampleTimeline,
      apple_events: [
        {
          title: "連休イベント",
          start_time: "2026-08-20T00:00:00",
          end_time: "2026-08-22T00:00:00",
          location: null,
          all_day: true,
          source: "apple",
        },
      ],
    } as any);
    render(<PlannerPage />);

    const cells = await screen.findAllByText("◐ 連休イベント");
    expect(cells).toHaveLength(3);
    expect(screen.queryByText("終日")).not.toBeInTheDocument();
  });

  it("shows a single-day all-day event once", async () => {
    mockGetTimeline.mockResolvedValue({
      ...sampleTimeline,
      apple_events: [
        {
          title: "誕生日",
          start_time: "2026-08-20T00:00:00",
          end_time: "2026-08-20T00:00:00",
          location: null,
          all_day: true,
          source: "apple",
        },
      ],
    } as any);
    render(<PlannerPage />);

    const cells = await screen.findAllByText("◐ 誕生日");
    expect(cells).toHaveLength(1);
  });

  it("navigates to the previous month and refetches", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByLabelText("前の月"));

    const { prevMonthLabel } = getDates();
    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByText(prevMonthLabel)).toBeInTheDocument();
  });

  it("switches to week view, shows the current week, and navigates", async () => {
    const { now, weekLabel, prevWeekLabel } = getDates();
    const user = userEvent.setup();
    const currentDay = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    mockGetTimeline.mockResolvedValue({
      ...sampleTimeline,
      ai_proposals: [
        {
          ...sampleTimeline.ai_proposals[0],
          start_time: `${currentDay}T10:00:00`,
        },
      ],
    } as any);
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("button", { name: "週" }));

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByRole("button", { name: "週" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(weekLabel)).toBeInTheDocument();
    expect(screen.getByText(/歯科検診/)).toBeInTheDocument();

    await user.click(screen.getByLabelText("前の週"));

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(3);
    });
    expect(screen.getByText(prevWeekLabel)).toBeInTheDocument();
  });

  it("switches back to month view and refetches", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("button", { name: "週" }));
    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(2);
    });

    await user.click(screen.getByRole("button", { name: "月" }));
    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(3);
    });
    expect(screen.getByRole("button", { name: "月" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("opens the detail panel for a selected AI proposal and rejects it", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(screen.getByText(/歯科検診/)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/歯科検診/));

    expect(screen.getByText("AI提案の編集")).toBeInTheDocument();
    expect(screen.getByText("最近のノートに予約希望があったため")).toBeInTheDocument();

    mockReject.mockResolvedValue({ ...sampleTimeline.ai_proposals[0], status: "rejected" } as any);
    await user.click(screen.getByRole("button", { name: "却下" }));

    await waitFor(() => {
      expect(mockReject).toHaveBeenCalledWith("pp-1");
    });
  });

  it("promotes the selected proposal", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(screen.getByText(/歯科検診/)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/歯科検診/));
    mockPromote.mockResolvedValue({
      ...sampleTimeline.ai_proposals[0],
      status: "promoted",
      promoted_at: "2026-08-19T00:00:00Z",
    } as any);
    await user.click(screen.getByRole("button", { name: "Appleに登録" }));

    await waitFor(() => {
      expect(mockPromote).toHaveBeenCalledWith("pp-1");
    });
  });

  it("saves edits to the selected proposal", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(screen.getByText(/歯科検診/)).toBeInTheDocument();
    });

    await user.click(screen.getByText(/歯科検診/));
    const titleInput = screen.getByLabelText("タイトル");
    await user.clear(titleInput);
    await user.type(titleInput, "歯科検診(変更)");
    mockUpdate.mockResolvedValue({ ...sampleTimeline.ai_proposals[0], title: "歯科検診(変更)" } as any);
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(mockUpdate).toHaveBeenCalledWith("pp-1", expect.objectContaining({ title: "歯科検診(変更)" }));
    });
  });

  it("generates proposals via the generate button", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "AI提案を生成" })).toBeInTheDocument();
    });

    mockGenerate.mockResolvedValue({ generated: 2, proposals: [] } as any);
    await user.click(screen.getByRole("button", { name: "AI提案を生成" }));

    await waitFor(() => {
      expect(mockGenerate).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("AI提案を2件生成しました")).toBeInTheDocument();
  });

  it("shows the apple error banner when present", async () => {
    mockGetTimeline.mockResolvedValue({
      ...sampleTimeline,
      apple_error: "EventKit unavailable",
    } as any);
    render(<PlannerPage />);

    await waitFor(() => {
      expect(screen.getByText(/EventKit unavailable/)).toBeInTheDocument();
    });
  });
});
