import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { HealthcareScatterChart } from "./HealthcareScatterChart";
import type { HealthcareCorrelationResponse } from "../../api/types";

function makeCorr(overrides: Partial<HealthcareCorrelationResponse> = {}): HealthcareCorrelationResponse {
  return {
    metric_x: "steps",
    metric_y: "sleep",
    x_label: "歩数",
    y_label: "睡眠時間",
    x_unit: "count",
    y_unit: "h",
    x_type: "HKQuantityTypeIdentifierStepCount",
    y_type: "HKCategoryTypeIdentifierSleepAnalysis",
    start_date: "2026-08-10",
    end_date: "2026-08-14",
    granularity: "day",
    n: 5,
    pearson_r: 0.95,
    regression_slope: 0.001,
    regression_intercept: 3.0,
    points: [
      { date: "2026-08-10", x: 3000, y: 6 },
      { date: "2026-08-11", x: 3500, y: 6.5 },
      { date: "2026-08-12", x: 4000, y: 7 },
      { date: "2026-08-13", x: 4500, y: 7.5 },
      { date: "2026-08-14", x: 5000, y: 8 },
    ],
    ...overrides,
  };
}

describe("HealthcareScatterChart", () => {
  it("renders points, regression line and pearson", () => {
    const data = makeCorr();
    const { container } = render(<HealthcareScatterChart data={data} />);
    expect(screen.getByText(/r = 0.95/)).toBeInTheDocument();
    expect(screen.getByText(/強い正の相関/)).toBeInTheDocument();
    expect(screen.getByText(/n = 5/)).toBeInTheDocument();
    // 5 points -> 5 circles
    const circles = container.querySelectorAll("circle");
    expect(circles.length).toBe(5);
    // regression line is a dashed line with stroke #3b82f6
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    const lines = svg!.querySelectorAll("line");
    // at least 7 lines: 3 x-grid +3 y-grid +1 regression
    expect(lines.length).toBeGreaterThanOrEqual(7);
  });

  it("shows empty state when no points", () => {
    const data = makeCorr({ points: [], n: 0, pearson_r: null, regression_slope: null, regression_intercept: null });
    render(<HealthcareScatterChart data={data} />);
    expect(screen.getByText(/両方の指標が揃った日がありません/)).toBeInTheDocument();
  });

  it("handles n=1 without pearson", () => {
    const data = makeCorr({
      points: [{ date: "2026-08-20", x: 120, y: 7.8 }],
      n: 1,
      pearson_r: null,
      regression_slope: null,
      regression_intercept: null,
    });
    render(<HealthcareScatterChart data={data} />);
    expect(screen.getByText(/r = —/)).toBeInTheDocument();
    expect(screen.getByText(/n = 1/)).toBeInTheDocument();
  });

  it("handles negative correlation", () => {
    const data = makeCorr({
      points: [
        { date: "2026-08-10", x: 3000, y: 8 },
        { date: "2026-08-11", x: 3500, y: 7.5 },
        { date: "2026-08-12", x: 4000, y: 7 },
      ],
      n: 3,
      pearson_r: -0.98,
    });
    render(<HealthcareScatterChart data={data} />);
    expect(screen.getByText(/r = -0.98/)).toBeInTheDocument();
    expect(screen.getByText(/強い負の相関/)).toBeInTheDocument();
  });
});
