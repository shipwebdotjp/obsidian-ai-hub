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
  getDashboardDayDetails,
  getDashboardStats,
} from "../../api/client";

const mockGetDashboardHome = vi.mocked(getDashboardHome);
const mockGetDashboardBrowse = vi.mocked(getDashboardBrowse);
const mockGetDashboardSummary = vi.mocked(getDashboardSummary);
const mockGetDashboardDayDetails = vi.mocked(getDashboardDayDetails);
const mockGetDashboardStats = vi.mocked(getDashboardStats);

const sampleHomeResponse = {
  this_month_summary: {
    summary_id: "sum_this_month",
    period_type: "month" as const,
    period_key: "2026-07",
    period_start: "2026-07-01",
    period_end: "2026-07-31",
    summary: "July Monthly Plan",
    keywords: [],
    mood: null,
    sleep_raw: null,
    sleep_hours: null,
    topics: ["LLM・AI活用"],
    projects: [],
    people: [],
    items: [],
  },
  latest_week_summary: {
    summary_id: "sum_latest_week",
    period_type: "week" as const,
    period_key: "2026-W29",
    period_start: "2026-07-13",
    period_end: "2026-07-19",
    summary: "Week 29 Wrapup",
    keywords: [],
    mood: null,
    sleep_raw: null,
    sleep_hours: null,
    topics: ["ソフトウェア開発"],
    projects: [],
    people: [],
    items: [],
  },
  yesterday_summary: {
    summary_id: "sum_yesterday",
    period_type: "day" as const,
    period_key: "2026-07-19",
    period_start: "2026-07-19",
    period_end: "2026-07-19",
    summary: "Yesterday Summary",
    keywords: [],
    mood: "good",
    sleep_raw: "7h",
    sleep_hours: 7.0,
    topics: [],
    projects: [],
    people: [],
    items: [],
  },
  today_activity: {
    date: "2026-07-20",
    active_minutes: 60.0,
    inactive_minutes: 540.0,
    logs: [
      {
        activity_id: "act_1",
        occurred_at: "2026-07-20T10:00:00",
        app_name: "VS Code",
        window_title: "types.ts",
        summary: "Coding summary",
        category: "開発",
        keywords: ["TypeScript"],
      },
    ],
  },
};

const sampleBrowseResponse = {
  selectable_years: ["2026"],
  selected_year: "2026",
  selected_month: null,
  months: [sampleHomeResponse.this_month_summary],
  weeks: [sampleHomeResponse.latest_week_summary],
  days: [],
};

const sampleStatsResponse = {
  granularity: "day" as const,
  buckets: [
    {
      key: "2026-07-20",
      display_label: "07/20",
      start_date: "2026-07-20",
      end_date: "2026-07-20",
      active_minutes: 60.0,
      inactive_minutes: 540.0,
      daily_summary_count: 1,
      topic_counts: { "LLM・AI活用": 1 },
      keyword_counts: { TypeScript: 1 },
    },
  ],
  candidate_topics: ["LLM・AI活用"],
  candidate_keywords: ["TypeScript"],
};

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders home screen metrics and logs on load", async () => {
  mockGetDashboardHome.mockResolvedValue(sampleHomeResponse);

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("今月の月次サマリ")).toBeInTheDocument();
    expect(screen.getByText("July Monthly Plan")).toBeInTheDocument();
    expect(screen.getByText("Week 29 Wrapup")).toBeInTheDocument();
    expect(screen.getByText("Yesterday Summary")).toBeInTheDocument();
  });

  expect(screen.getByText("Coding summary")).toBeInTheDocument();
  expect(screen.getByText("VS Code")).toBeInTheDocument();
});

it("switches to browse tab and lists summaries", async () => {
  mockGetDashboardHome.mockResolvedValue(sampleHomeResponse);
  mockGetDashboardBrowse.mockResolvedValue(sampleBrowseResponse);

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("今月の月次サマリ")).toBeInTheDocument();
  });

  // Click on "一覧" tab
  await userEvent.click(screen.getByRole("button", { name: "一覧" }));

  await waitFor(() => {
    expect(screen.getByText("月次サマリ (1件)")).toBeInTheDocument();
    expect(screen.getByText("週次サマリ (1件)")).toBeInTheDocument();
  });
});

it("switches to stats tab and renders charts", async () => {
  mockGetDashboardHome.mockResolvedValue(sampleHomeResponse);
  mockGetDashboardStats.mockResolvedValue(sampleStatsResponse);

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("今月の月次サマリ")).toBeInTheDocument();
  });

  // Click on "統計" tab
  await userEvent.click(screen.getByRole("button", { name: "統計" }));

  await waitFor(() => {
    expect(screen.getByText("トピック出現率の推移")).toBeInTheDocument();
    expect(screen.getByText("キーワード出現率の推移")).toBeInTheDocument();
    expect(screen.getByText("活動カバー時間と非活動時間の比率")).toBeInTheDocument();
  });
});
