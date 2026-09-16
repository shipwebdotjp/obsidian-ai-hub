import { describe, expect, it } from "vitest";
import type { CodingRun } from "../../../api/coding";
import {
  formatCost,
  formatTokenBreakdown,
  formatTokens,
  hasCumulativeUsage,
  runUsageSummary,
  sessionUsageSummary,
} from "./codingUsage";

function run(overrides: Partial<CodingRun>): CodingRun {
  return {
    run_id: "crun_1",
    session_id: "cses_1",
    user_message_id: "cmsg_1",
    orchestrator_message_id: null,
    worker_message_id: null,
    status: "completed",
    hitl_run_id: null,
    dirty_tree_at_start: null,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: "2026-01-01T00:01:00Z",
    ...overrides,
  };
}

describe("runUsageSummary", () => {
  it("累積ブロックがあればそれを優先しコンテキスト使用量はmaxを使う", () => {
    const summary = runUsageSummary(
      run({
        diagnostics: {
          usage: { input: 10, output: 2, total: 12 },
          usage_cumulative: {
            input: 150,
            output: 25,
            total: 210,
            cached: 40,
            used_max: 2000,
            size_max: 200000,
            cost: { amount: 0.03, currency: "USD" },
          },
          worker_attempt_count: 2,
        },
      }),
    );

    expect(summary).toEqual({
      input: 150,
      output: 25,
      total: 210,
      cached: 40,
      used: 2000,
      size: 200000,
      costAmount: 0.03,
      costCurrency: "USD",
    });
  });

  it("累積ブロックが無ければ最終試行値へフォールバックする", () => {
    const summary = runUsageSummary(
      run({
        diagnostics: {
          usage: { input: 100, output: 20, total: 120, used: 900, size: 200000 },
        },
      }),
    );

    expect(summary?.input).toBe(100);
    expect(summary?.used).toBe(900);
    expect(summary?.size).toBe(200000);
  });

  it("usageが無ければnullを返す", () => {
    expect(runUsageSummary(run({ diagnostics: { acp_session_id: "s1" } }))).toBeNull();
    expect(runUsageSummary(run({}))).toBeNull();
    expect(runUsageSummary(null)).toBeNull();
  });
});

describe("hasCumulativeUsage", () => {
  it("累積ブロックの有無を判定する", () => {
    expect(
      hasCumulativeUsage(run({ diagnostics: { usage_cumulative: { total: 5 } } })),
    ).toBe(true);
    expect(hasCumulativeUsage(run({ diagnostics: { usage: { total: 5 } } }))).toBe(false);
  });
});

describe("sessionUsageSummary", () => {
  it("runをまたいで加算しコンテキスト使用量はmaxを取る", () => {
    const summary = sessionUsageSummary([
      run({
        run_id: "r1",
        diagnostics: {
          usage_cumulative: {
            input: 100,
            output: 10,
            total: 110,
            cached: 5,
            used_max: 50000,
            size_max: 200000,
            cost: { amount: 0.01, currency: "USD" },
          },
        },
      }),
      run({
        run_id: "r2",
        diagnostics: {
          usage_cumulative: {
            input: 200,
            output: 20,
            total: 220,
            cached: 15,
            used_max: 8000,
            size_max: 200000,
            cost: { amount: 0.02, currency: "USD" },
          },
        },
      }),
    ]);

    expect(summary?.input).toBe(300);
    expect(summary?.output).toBe(30);
    expect(summary?.total).toBe(330);
    expect(summary?.cached).toBe(20);
    expect(summary?.used).toBe(50000);
    expect(summary?.size).toBe(200000);
    expect(summary?.costAmount).toBeCloseTo(0.03);
  });

  it("usageが一つも無ければnullを返す", () => {
    expect(sessionUsageSummary([run({}), null, undefined])).toBeNull();
  });
});

describe("formatTokens", () => {
  it("桁に応じてk/Mへ省略する", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1234)).toBe("1.2k");
    expect(formatTokens(12345)).toBe("12k");
    expect(formatTokens(1_234_567)).toBe("1.23M");
  });
});

describe("formatTokenBreakdown", () => {
  it("入力/キャッシュ読取/出力/合計の順に整形する", () => {
    const text = formatTokenBreakdown({
      input: 1200,
      cached: 300,
      output: 40,
      total: 1500,
    });
    expect(text).toBe("入力 1.2k / キャッシュ読取 300 / 出力 40 / 合計 1.5k");
  });
});

describe("formatCost", () => {
  it("通貨があれば付与する", () => {
    expect(formatCost(0.03, "USD")).toBe("0.03 USD");
    expect(formatCost(5)).toBe("5");
  });
});
