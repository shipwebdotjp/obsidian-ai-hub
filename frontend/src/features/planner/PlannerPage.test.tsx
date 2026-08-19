import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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
    { title: "終日予定", start_time: null, end_time: null, location: null, all_day: true, source: "apple" },
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
  vi.clearAllMocks();
  mockGetTimeline.mockResolvedValue(sampleTimeline as any);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("PlannerPage", () => {
  it("loads the week timeline and renders all layers", async () => {
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText("Appleミーティング")).toBeInTheDocument();
    expect(screen.getByText("終日予定")).toBeInTheDocument();
    expect(screen.getByText(/リマインダーA/)).toBeInTheDocument();
    expect(screen.getByText(/定期掃除/)).toBeInTheDocument();
    expect(screen.getByText(/確認待ち予定/)).toBeInTheDocument();
    expect(screen.getByText(/歯科検診/)).toBeInTheDocument();
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

  it("navigates to the previous week and refetches", async () => {
    const user = userEvent.setup();
    render(<PlannerPage />);

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByLabelText("前の週"));

    await waitFor(() => {
      expect(mockGetTimeline).toHaveBeenCalledTimes(2);
    });
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