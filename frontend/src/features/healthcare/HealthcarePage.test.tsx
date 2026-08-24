import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import HealthcarePage from "./HealthcarePage";

vi.mock("../../api/client", () => ({
  getHealthcareOverview: vi.fn(),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  },
}));

import { getHealthcareOverview } from "../../api/client";
import type { HealthcareOverviewResponse } from "../../api/types";

const mockGetOverview = vi.mocked(getHealthcareOverview);

function makeBucket(key: string, display_label: string, value: number | null) {
  return {
    key,
    display_label,
    start_date: key,
    end_date: key,
    value,
    avg: value,
    min: value,
    max: value,
    sum: value,
    count: value !== null ? 1 : 0,
  };
}

const sampleOverview: HealthcareOverviewResponse = {
  start_date: "2026-08-01",
  end_date: "2026-08-07",
  granularity: "day",
  metrics: [
    {
      key: "steps",
      label: "歩数",
      type: "HKQuantityTypeIdentifierStepCount",
      unit: "count",
      aggregation: "sum",
      latest_value: 5000,
      previous_value: 4000,
      delta_pct: 25,
      buckets: [
        makeBucket("2026-08-01", "08/01", 3000),
        makeBucket("2026-08-02", "08/02", 4000),
        makeBucket("2026-08-03", "08/03", 5000),
        makeBucket("2026-08-04", "08/04", null),
        makeBucket("2026-08-05", "08/05", null),
        makeBucket("2026-08-06", "08/06", null),
        makeBucket("2026-08-07", "08/07", null),
      ],
    },
    {
      key: "heart_rate",
      label: "心拍数",
      type: "HKQuantityTypeIdentifierHeartRate",
      unit: "count/min",
      aggregation: "avg",
      latest_value: 72,
      previous_value: 70,
      delta_pct: 2.9,
      buckets: [
        makeBucket("2026-08-01", "08/01", 70),
        makeBucket("2026-08-02", "08/02", 71),
        makeBucket("2026-08-03", "08/03", 72),
        makeBucket("2026-08-04", "08/04", null),
        makeBucket("2026-08-05", "08/05", null),
        makeBucket("2026-08-06", "08/06", null),
        makeBucket("2026-08-07", "08/07", null),
      ],
    },
  ],
};

const emptyOverview: HealthcareOverviewResponse = {
  start_date: "2026-08-01",
  end_date: "2026-08-07",
  granularity: "day",
  metrics: [
    {
      key: "steps",
      label: "歩数",
      type: "HKQuantityTypeIdentifierStepCount",
      unit: "count",
      aggregation: "sum",
      latest_value: null,
      previous_value: null,
      delta_pct: null,
      buckets: [
        makeBucket("2026-08-01", "08/01", null),
        makeBucket("2026-08-02", "08/02", null),
        makeBucket("2026-08-03", "08/03", null),
        makeBucket("2026-08-04", "08/04", null),
        makeBucket("2026-08-05", "08/05", null),
        makeBucket("2026-08-06", "08/06", null),
        makeBucket("2026-08-07", "08/07", null),
      ],
    },
  ],
};

describe("HealthcarePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders title and loads data on mount", async () => {
    mockGetOverview.mockResolvedValue(sampleOverview);
    render(<HealthcarePage />);
    expect(screen.getByText("ヘルスケア")).toBeInTheDocument();
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalled());
    expect(await screen.findByText("歩数")).toBeInTheDocument();
    expect(screen.getByText("心拍数")).toBeInTheDocument();
  });

  it("shows loading state", () => {
    mockGetOverview.mockReturnValue(new Promise(() => {}));
    render(<HealthcarePage />);
    expect(screen.getByText(/ロード中/)).toBeInTheDocument();
  });

  it("shows error on API failure", async () => {
    const { ApiError } = await import("../../api/client");
    mockGetOverview.mockRejectedValue(new ApiError(500, "server error"));
    render(<HealthcarePage />);
    await waitFor(() => expect(screen.getByText(/server error/)).toBeInTheDocument());
  });

  it("handles preset buttons and reloads", async () => {
    mockGetOverview.mockResolvedValue(sampleOverview);
    render(<HealthcarePage />);
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalledTimes(1));

    const user = userEvent.setup();
    mockGetOverview.mockResolvedValue(sampleOverview);
    await user.click(screen.getByText("7日間"));
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalledTimes(2));

    await user.click(screen.getByText("90日間"));
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalledTimes(3));
  });

  it("shows empty state when no data", async () => {
    mockGetOverview.mockResolvedValue(emptyOverview);
    render(<HealthcarePage />);
    await waitFor(() => expect(screen.getByText(/まだありません/)).toBeInTheDocument());
    expect(screen.getByText(/export をインポート/)).toBeInTheDocument();
  });

  it("displays latest value and delta", async () => {
    mockGetOverview.mockResolvedValue(sampleOverview);
    render(<HealthcarePage />);
    await waitFor(() => expect(screen.getByTestId("healthcare-latest-steps")).toBeInTheDocument());
    expect(screen.getByTestId("healthcare-latest-steps").textContent).toContain("5,000");
    expect(screen.getByTestId("healthcare-delta-steps").textContent).toContain("25");
  });

  it("applies custom date range on button click", async () => {
    mockGetOverview.mockResolvedValue(sampleOverview);
    render(<HealthcarePage />);
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalledTimes(1));

    const user = userEvent.setup();
    const startInput = screen.getByLabelText("開始日");
    const endInput = screen.getByLabelText("終了日");
    await user.clear(startInput);
    await user.type(startInput, "2026-07-01");
    await user.clear(endInput);
    await user.type(endInput, "2026-07-31");
    await user.click(screen.getByText("適用"));
    await waitFor(() => expect(mockGetOverview).toHaveBeenCalledTimes(2));
    const lastCall = mockGetOverview.mock.calls[1]![0] as { start_date: string; end_date: string };
    expect(lastCall.start_date).toBe("2026-07-01");
    expect(lastCall.end_date).toBe("2026-07-31");
  });
});
