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
  getEditOptions: vi.fn(),
  updateSummary: vi.fn(),
  deleteSummary: vi.fn(),
  listPeople: vi.fn(),
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
  getEditOptions,
  updateSummary,
  deleteSummary,
  listPeople,
} from "../../api/client";
import type { DashboardStatsResponse } from "../../api/types";

const mockGetDashboardHome = vi.mocked(getDashboardHome);
const mockGetDashboardBrowse = vi.mocked(getDashboardBrowse);
const mockGetDashboardSummary = vi.mocked(getDashboardSummary);
const mockGetDashboardStats = vi.mocked(getDashboardStats);
const mockGetEditOptions = vi.mocked(getEditOptions);
const mockUpdateSummary = vi.mocked(updateSummary);
const mockDeleteSummary = vi.mocked(deleteSummary);
const mockListPeople = vi.mocked(listPeople);

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
  activity_categories: ["開発", "コミュニケーション", "その他"],
  hourly_category_buckets: Array.from({ length: 24 }, (_, i) => ({
    hour: i,
    total_log_count: 0,
    category_counts: {},
  })),
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

it("renders category heatmap in stats tab", async () => {
  const heatmapResponse: DashboardStatsResponse = {
    ...sampleStatsResponse,
    hourly_category_buckets: Array.from({ length: 24 }, (_, i) => {
      const category_counts: Record<string, number> = {};
      if (i === 10) {
        category_counts["開発"] = 2;
        category_counts["コミュニケーション"] = 1;
      } else if (i === 15) {
        category_counts["その他"] = 1;
      }
      return {
        hour: i,
        total_log_count: i === 10 ? 3 : i === 15 ? 1 : 0,
        category_counts,
      };
    }),
  };
  mockGetDashboardStats.mockResolvedValue(heatmapResponse);

  render(<SummaryDashboardPage />);

  await userEvent.click(screen.getByRole("button", { name: "統計" }));
  await waitFor(() => {
    expect(screen.getByText("時間帯 × カテゴリー ヒートマップ")).toBeInTheDocument();
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
  await waitFor(() => {
    expect(screen.getByText(/2026\/07\/19/)).toBeInTheDocument();
  });
  await userEvent.click(screen.getByText(/2026\/07\/19/));
  await screen.findByText("First activity");

  expect(screen.getAllByText("activities")).toHaveLength(1);
  const detailText = screen.getByText("First activity").closest("section")?.parentElement?.textContent;
  expect(detailText).toMatch(/activitiesFirst activitySecond activityhighlightsA highlight/);
});

it("shows edit and delete buttons in summary detail view", async () => {
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
    summary: "昨日のサマリ",
    keywords: [],
    topics: [],
    projects: [],
    people: [],
    mood: null,
    sleep_raw: null,
    sleep_hours: null,
    items: [],
  });

  render(<SummaryDashboardPage />);

  await userEvent.click(screen.getByRole("button", { name: "一覧" }));
  // Wait for browse data to load and day button to appear (formatted as 2026/07/19(土))
  await waitFor(() => {
    expect(screen.getByText(/2026\/07\/19/)).toBeInTheDocument();
  });
  await userEvent.click(screen.getByText(/2026\/07\/19/));
  await screen.findByText("昨日のサマリ");

  expect(screen.getByRole("button", { name: "編集" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "削除" })).toBeInTheDocument();
});

it("shows delete confirmation dialog when delete is clicked", async () => {
  mockGetDashboardBrowse.mockResolvedValue({
    ...sampleBrowseResponse,
    selected_month: "2026-07",
    days: [
      {
        date: "2026-07-19",
        has_summary: true,
        summary_id: "summary-1",
        summary: "Delete me",
        topics: [],
      },
    ],
  });
  mockGetDashboardSummary.mockResolvedValue({
    summary_id: "summary-1",
    period_type: "day",
    period_key: "2026-07-19",
    summary: "Delete me summary",
    keywords: [],
    topics: [],
    projects: [],
    people: [],
    mood: null,
    sleep_raw: null,
    sleep_hours: null,
    items: [],
  });

  render(<SummaryDashboardPage />);

  await userEvent.click(screen.getByRole("button", { name: "一覧" }));
  await waitFor(() => {
    expect(screen.getByText(/2026\/07\/19/)).toBeInTheDocument();
  });
  await userEvent.click(screen.getByText(/2026\/07\/19/));
  await screen.findByText("Delete me summary");

  await userEvent.click(screen.getByRole("button", { name: "削除" }));
  expect(screen.getByText("この操作は取り消せません。本当に削除しますか？")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "削除する" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "やめる" })).toBeInTheDocument();
});

it("enters edit mode and loads edit options", async () => {
  mockGetDashboardBrowse.mockResolvedValue({
    ...sampleBrowseResponse,
    selected_month: "2026-07",
    days: [
      {
        date: "2026-07-19",
        has_summary: true,
        summary_id: "summary-1",
        summary: "Test",
        topics: [],
      },
    ],
  });
  mockGetDashboardSummary.mockResolvedValue({
    summary_id: "summary-1",
    period_type: "day",
    period_key: "2026-07-19",
    summary: "Test summary",
    keywords: ["kw1"],
    topics: ["LLM・AI活用"],
    projects: [],
    people: [],
    mood: "良い",
    sleep_raw: "7h",
    sleep_hours: 7,
    items: [],
  });
  mockGetEditOptions.mockResolvedValue({
    topics: ["LLM・AI活用", "ソフトウェア開発"],
    item_kinds: { day: ["highlights", "activities"], week: [], month: [] },
  });
  mockListPeople.mockResolvedValue([]);

  render(<SummaryDashboardPage />);

  await userEvent.click(screen.getByRole("button", { name: "一覧" }));
  await waitFor(() => {
    expect(screen.getByText(/2026\/07\/19/)).toBeInTheDocument();
  });
  await userEvent.click(screen.getByText(/2026\/07\/19/));
  await screen.findByText("Test summary");

  await userEvent.click(screen.getByRole("button", { name: "編集" }));

  await waitFor(() => {
    expect(mockGetEditOptions).toHaveBeenCalled();
    expect(mockListPeople).toHaveBeenCalled();
  });

  // Edit form should be visible
  expect(screen.getByRole("button", { name: "保存" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "キャンセル" })).toBeInTheDocument();
});
