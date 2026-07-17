import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import SummaryDashboardPage from "./SummaryDashboardPage";

vi.mock("../../api/client", () => ({
  listSummaries: vi.fn(),
  getSummary: vi.fn(),
  getSummaryOptions: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import {
  listSummaries,
  getSummary,
  getSummaryOptions,
} from "../../api/client";

const mockListSummaries = vi.mocked(listSummaries);
const mockGetSummary = vi.mocked(getSummary);
const mockGetSummaryOptions = vi.mocked(getSummaryOptions);

const sampleSummary = {
  summary_id: "sum_20260713_day",
  period_type: "day" as const,
  period_key: "2026-07-13",
  period_start: "2026-07-13",
  period_end: "2026-07-13",
  generated_at: "2026-07-13T22:00:00",
  summary: "Test summary",
  keywords: [],
  mood: "good",
  sleep_raw: "7h",
  sleep_hours: 7,
  topics: ["LLM・AI活用"],
  projects: ["Project A"],
  people: [{ name: "Alice", note: "met" }],
};

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders summary list and options on load", async () => {
  mockGetSummaryOptions.mockResolvedValue({
    period_types: ["day", "week", "month"],
    topics: ["LLM・AI活用"],
    projects: ["Project A"],
    people: ["Alice"],
  });
  mockListSummaries.mockResolvedValue({ items: [sampleSummary], total: 1 });

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("Test summary")).toBeInTheDocument();
  });
  expect(screen.getByText("(1 件)")).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "LLM・AI活用" })).toBeInTheDocument();
});

it("shows detail when a summary is selected", async () => {
  mockGetSummaryOptions.mockResolvedValue({
    period_types: ["day", "week", "month"],
    topics: [],
    projects: [],
    people: [],
  });
  mockListSummaries.mockResolvedValue({ items: [sampleSummary], total: 1 });
  mockGetSummary.mockResolvedValue({
    ...sampleSummary,
    items: [
      {
        summary_item_id: "item_1",
        kind: "highlights",
        body: "Highlight text",
        display_order: 0,
      },
    ],
  });

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("Test summary")).toBeInTheDocument();
  });

  await userEvent.click(screen.getByText("Test summary"));

  await waitFor(() => {
    expect(screen.getByText("Highlight text")).toBeInTheDocument();
  });
});

it("shows empty message when no summaries match", async () => {
  mockGetSummaryOptions.mockResolvedValue({
    period_types: ["day", "week", "month"],
    topics: [],
    projects: [],
    people: [],
  });
  mockListSummaries.mockResolvedValue({ items: [], total: 0 });

  render(<SummaryDashboardPage />);

  await waitFor(() => {
    expect(screen.getByText("該当するサマリはありません。")).toBeInTheDocument();
  });
});
