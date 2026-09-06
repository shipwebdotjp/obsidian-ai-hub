import { describe, expect, it } from "vitest";
import type { AgentLiveToolCall, AgentRun, SlashCandidate } from "../../api/types";
import {
  buildRunsByMessageId,
  buildRunsByUserMessageId,
  filterSlashCandidates,
  getLiveStatusClass,
  getLiveStatusLabel,
  LIVE_RESULT_MAX_CHARS,
  matchesLiveToolCall,
  toClientTemplateCandidates,
  truncateLiveResult,
} from "./agentViewUtils";

function candidate(overrides: Partial<SlashCandidate>): SlashCandidate {
  return { kind: "skill", name: "x", ...overrides } as SlashCandidate;
}

describe("filterSlashCandidates", () => {
  const candidates = [
    candidate({ kind: "skill", name: "pdftomd" }),
    candidate({ kind: "template", name: "daily", content: "daily content" }),
    candidate({ kind: "template", name: "daily-review", content: "review content" }),
  ];

  it("スラッシュ開始でなければ空を返す", () => {
    expect(filterSlashCandidates(candidates, "hello")).toEqual([]);
    expect(filterSlashCandidates(candidates, "")).toEqual([]);
  });

  it("クエリなしでは全候補を上限付きで返す", () => {
    expect(filterSlashCandidates(candidates, "/")).toHaveLength(3);
  });

  it("前方一致を部分一致より優先して返す", () => {
    const res = filterSlashCandidates(
      [candidate({ name: "xdaily" }), candidate({ name: "dailyx" })],
      "/daily",
    );
    expect(res.map((c) => c.name)).toEqual(["dailyx", "xdaily"]);
  });

  it("template 明示指定ではテンプレートのみに絞る", () => {
    const res = filterSlashCandidates(candidates, "/template daily");
    expect(res.every((c) => c.kind === "template")).toBe(true);
    expect(res.map((c) => c.name)).toEqual(["daily", "daily-review"]);
  });

  it("template 明示指定かつクエリなしではテンプレートを上限8件で返す", () => {
    const many = Array.from({ length: 10 }, (_, i) =>
      candidate({ kind: "template", name: `t${i}` }),
    );
    expect(filterSlashCandidates(many, "/template ").map((c) => c.name)).toEqual(
      Array.from({ length: 8 }, (_, i) => `t${i}`),
    );
  });
});

describe("matchesLiveToolCall", () => {
  const tc = {
    id: "id1",
    call_key: "key1",
    call_id: "cid1",
  } as AgentLiveToolCall;

  it("call_key / call_id / id のいずれか一致で真", () => {
    expect(matchesLiveToolCall(tc, "key1")).toBe(true);
    expect(matchesLiveToolCall(tc, undefined, "cid1")).toBe(true);
    expect(matchesLiveToolCall(tc, "id1")).toBe(true);
    expect(matchesLiveToolCall(tc, "other", "other")).toBe(false);
    expect(matchesLiveToolCall(tc)).toBe(false);
  });
});

describe("live status labels", () => {
  it("日本語ラベルとクラスを返す", () => {
    expect(getLiveStatusLabel("succeeded")).toBe("成功");
    expect(getLiveStatusLabel("preparing")).toBe("準備中…");
    expect(getLiveStatusClass("failed")).toContain("rose");
  });
});

describe("run maps", () => {
  const runs = [
    { run_id: "r1", assistant_message_id: "m1", user_message_id: "u1" },
    { run_id: "r2", assistant_message_id: null, user_message_id: null },
  ] as AgentRun[];

  it("メッセージIDからrunを引ける", () => {
    expect(buildRunsByMessageId(runs).get("m1")?.run_id).toBe("r1");
    expect(buildRunsByUserMessageId(runs).get("u1")?.run_id).toBe("r1");
    expect(buildRunsByMessageId(runs).size).toBe(1);
  });
});

describe("truncateLiveResult", () => {
  it("上限超過分を切り詰める", () => {
    const long = "a".repeat(LIVE_RESULT_MAX_CHARS + 10);
    const out = truncateLiveResult(long);
    expect(out.endsWith("\n…(truncated for live view)")).toBe(true);
    expect(truncateLiveResult("short")).toBe("short");
  });
});

describe("toClientTemplateCandidates", () => {
  it("テンプレートを候補形式へ変換する", () => {
    const templates = [
      { template_id: "t1", name: "n1", content: "c1" },
    ] as unknown as Parameters<typeof toClientTemplateCandidates>[0];
    const out = toClientTemplateCandidates(templates);
    expect(out).toEqual([
      { kind: "template", name: "n1", description: "c1", template_id: "t1", content: "c1" },
    ]);
  });
});
