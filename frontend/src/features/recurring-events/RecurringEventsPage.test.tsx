import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BrowserRouter } from "react-router-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import RecurringEventsPage from "./RecurringEventsPage";
import * as api from "./recurringEventsApi";

vi.mock("./recurringEventsApi");

const mockSeries = [
  {
    series_id: "res_001",
    type_id: "ret_001",
    type_name: "散髪",
    interval_value: 1,
    interval_unit: "month" as const,
    properties: [],
    properties_dict: {},
    latest_executed_on: "2025-03-01",
    next_due_date: "2025-04-01",
    elapsed_days: 30,
    total_count: 5,
    latest_photo_thumbnail: null,
    latest_note: "カットのみ",
    records: [
      {
        record_id: "rer_001",
        series_id: "res_001",
        executed_on: "2025-03-01",
        note: "カットのみ",
        media_id: null,
        media: null,
        count_contribution: 1,
        is_start_record: true,
        created_at: "2025-03-01T10:00:00Z",
        updated_at: "2025-03-01T10:00:00Z",
      },
    ],
    created_at: "2025-03-01T10:00:00Z",
    updated_at: "2025-03-01T10:00:00Z",
  },
];

describe("RecurringEventsPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
      this.open = true;
    });
    HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) {
      this.open = false;
    });
  });

  it("renders page title and series cards", async () => {
    vi.mocked(api.listSeries).mockResolvedValue(mockSeries);

    render(
      <BrowserRouter>
        <RecurringEventsPage />
      </BrowserRouter>
    );

    expect(screen.getByText("定期記録")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("散髪")).toBeInTheDocument();
    });

    expect(screen.getByText(/推奨間隔: 1 月ごと/)).toBeInTheDocument();
    expect(screen.getByText("5回")).toBeInTheDocument();
    expect(screen.getByText("カットのみ")).toBeInTheDocument();
  });

  it("renders API yyyy-mm-dd dates with weekday display", async () => {
    vi.mocked(api.listSeries).mockResolvedValue(mockSeries);

    render(
      <BrowserRouter>
        <RecurringEventsPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("散髪")).toBeInTheDocument();
    });

    // 2025-03-01 is Saturday, 2025-04-01 is Tuesday.
    expect(screen.getByText("2025/03/01(土)")).toBeInTheDocument();
    expect(screen.getByText(/2025\/04\/01\(火\)/)).toBeInTheDocument();
  });

  it("opens create series modal when button clicked", async () => {
    vi.mocked(api.listSeries).mockResolvedValue([]);
    vi.mocked(api.listEventTypes).mockResolvedValue([
      {
        type_id: "ret_001",
        name: "散髪",
        properties: [],
        series_count: 0,
        created_at: "2025-03-01T10:00:00Z",
        updated_at: "2025-03-01T10:00:00Z",
      },
    ]);

    const user = userEvent.setup();
    render(
      <BrowserRouter>
        <RecurringEventsPage />
      </BrowserRouter>
    );

    await waitFor(() => {
      expect(screen.getByText("定期記録シリーズがありません。")).toBeInTheDocument();
    });

    const createBtn = screen.getByRole("button", { name: "＋ シリーズ作成" });
    await user.click(createBtn);

    await waitFor(() => {
      expect(screen.getByText("シリーズ新規作成")).toBeInTheDocument();
    });
  });
});
