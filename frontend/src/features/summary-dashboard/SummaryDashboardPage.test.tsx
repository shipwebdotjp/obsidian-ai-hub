import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SummaryDashboardPage from "./SummaryDashboardPage";

vi.mock("../../api/client", () => ({
  getDashboardHome: vi.fn(),
  getDashboardBrowse: vi.fn(),
  getDashboardSummary: vi.fn(),
  getDashboardDayDetails: vi.fn(),
  getDashboardStats: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import {
  getDashboardHome,
  getDashboardBrowse,
  getDashboardSummary,
  getDashboardStats,
} from "../../api/client";

const mockGetDashboardHome = vi.mocked(getDashboardHome);
const mockGetDashboardBrowse = vi.mocked(getDashboardBrowse);
const mockGetDashboardSummary = vi.mocked(getDashboardSummary);
const mockGetDashboardStats = vi.mocked(getDashboardStats);

const sampleHomeResponse = {
  this_month_summary: null,
  latest_week_summary: null,
  yesterday_summary: null,
  today_activity: {
    date: "2026-07-20",
    active_minutes: 0,
    inactive_minutes: 0,
    logs: [],
  },
};

const sampleBrowseResponse = {
  selectable_years: ["2026"],
  selected_year: "2026",
  selected_month: null,
  months: [],
  weeks: [],
  days: [],
};

const sampleStatsResponse = {
  granularity: "day" as const,
  buckets: [],
  candidate_topics: [],
  candidate_keywords: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  mockGetDashboardHome.mockResolvedValue(sampleHomeResponse);
  mockGetDashboardBrowse.mockResolvedValue(sampleBrowseResponse);
  mockGetDashboardStats.mockResolvedValue(sampleStatsResponse);
});

it("renders dashboard and supports tab navigation", async () => {
  render(<SummaryDashboardPage />);

  // Verify Home tab renders initially
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "ホーム" })).toBeInTheDocument();
  });

  // Navigate to Browse
  await userEvent.click(screen.getByRole("button", { name: "一覧" }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "一覧" })).toBeInTheDocument();
  });

  // Navigate to Stats
  await userEvent.click(screen.getByRole("button", { name: "統計" }));
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "統計" })).toBeInTheDocument();
  });
});

it("groups summary items by kind in their first-seen order", async () => {
  mockGetDashboardBrowse.mockResolvedValue({
    ...sampleBrowseResponse,
    selected_month: "2026-07",
    days: [
      {
        date: "2026-07-19",
        has_summary: true,
        summary_id: "summary-1",
        summary: "Yesterday",
        topics: [],
      },
    ],
  });
  mockGetDashboardSummary.mockResolvedValue({
    summary_id: "summary-1",
    period_type: "day",
    period_key: "2026-07-19",
    summary: "Yesterday",
    keywords: [],
    topics: [],
    projects: [],
    people: [],
    mood: null,
    sleep_raw: null,
    sleep_hours: null,
    items: [
      { summary_item_id: "1", kind: "activities", body: "First activity", display_order: 0 },
      { summary_item_id: "2", kind: "highlights", body: "A highlight", display_order: 0 },
      { summary_item_id: "3", kind: "activities", body: "Second activity", display_order: 1 },
    ],
  });

  render(<SummaryDashboardPage />);

  await userEvent.click(screen.getByRole("button", { name: "一覧" }));
  await userEvent.click(await screen.findByRole("button", { name: /2026-07-19/ }));
  await screen.findByText("First activity");

  expect(screen.getAllByText("activities")).toHaveLength(1);
  const detailText = screen.getByText("First activity").closest("section")?.parentElement?.textContent;
  expect(detailText).toMatch(/activitiesFirst activitySecond activityhighlightsA highlight/);
});
