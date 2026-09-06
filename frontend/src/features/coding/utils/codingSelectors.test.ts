import { describe, expect, it } from "vitest";
import type { CodingMessage, CodingOrchestratorToolCall, CodingRun } from "../../../api/coding";
import {
  buildRunById,
  getRunIdForUserMessage,
  groupToolCallsByMessageId,
  groupUnassociatedToolCallsByRunId,
  selectValidProjects,
} from "./codingSelectors";
import type { CodingProjectItem } from "../../../api/coding";

function toolCall(overrides: Partial<CodingOrchestratorToolCall>): CodingOrchestratorToolCall {
  return {
    call_id: "cotc_1",
    run_id: "crun_1",
    phase: "initial",
    phase_turn: 1,
    iteration: 1,
    call_index: 0,
    call_key: "1:1:0",
    orchestrator_message_id: null,
    tool_name: "web_search",
    args: {},
    result: null,
    status: "succeeded",
    started_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function run(overrides: Partial<CodingRun>): CodingRun {
  return {
    run_id: "crun_1",
    session_id: "cses_1",
    user_message_id: "cmsg_1",
    orchestrator_message_id: null,
    worker_message_id: null,
    status: "queued",
    hitl_run_id: null,
    dirty_tree_at_start: null,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

describe("selectValidProjects", () => {
  it("git リポジトリとして有効な項目だけを順序維持で返す", () => {
    const projects = [
      { project: { project_id: 1 }, is_valid_git_repo: true },
      { project: { project_id: 2 }, is_valid_git_repo: false },
      { project: { project_id: 3 }, is_valid_git_repo: true },
    ] as CodingProjectItem[];
    expect(selectValidProjects(projects).map((p) => p.project.project_id)).toEqual([1, 3]);
  });
});

describe("groupToolCallsByMessageId", () => {
  it("orchestrator_message_id 付きだけをメッセージごとに束ねる", () => {
    const map = groupToolCallsByMessageId([
      toolCall({ call_id: "a", orchestrator_message_id: "m1" }),
      toolCall({ call_id: "b", orchestrator_message_id: "m1" }),
      toolCall({ call_id: "c", orchestrator_message_id: null, run_id: "crun_x" }),
    ]);
    expect([...map.keys()]).toEqual(["m1"]);
    expect(map.get("m1")?.map((tc) => tc.call_id)).toEqual(["a", "b"]);
  });

  it("未定義入力では空マップを返す", () => {
    expect(groupToolCallsByMessageId(undefined).size).toBe(0);
  });
});

describe("groupUnassociatedToolCallsByRunId", () => {
  it("メッセージ未紐付けだけを run ごとに束ねる", () => {
    const map = groupUnassociatedToolCallsByRunId([
      toolCall({ call_id: "a", orchestrator_message_id: null, run_id: "crun_x" }),
      toolCall({ call_id: "b", orchestrator_message_id: "m1", run_id: "crun_x" }),
      toolCall({ call_id: "c", orchestrator_message_id: null, run_id: "crun_y" }),
    ]);
    expect([...map.keys()].sort()).toEqual(["crun_x", "crun_y"]);
    expect(map.get("crun_x")?.map((tc) => tc.call_id)).toEqual(["a"]);
  });
});

describe("buildRunById", () => {
  it("active/latest がセッション内 runs を上書きする", () => {
    const base = run({ run_id: "crun_1", status: "completed" });
    const active = run({ run_id: "crun_1", status: "running" });
    const latest = run({ run_id: "crun_2", status: "failed" });
    const map = buildRunById([base], active, latest);
    expect(map.get("crun_1")?.status).toBe("running");
    expect(map.get("crun_2")?.status).toBe("failed");
  });
});

describe("getRunIdForUserMessage", () => {
  it("msg.run_id > activeRun > latestRun の優先順位で返す", () => {
    const msg = { message_id: "cmsg_1", run_id: "crun_direct" } as CodingMessage;
    expect(getRunIdForUserMessage(msg, run({}), run({}))).toBe("crun_direct");

    const noDirect = { message_id: "cmsg_1" } as CodingMessage;
    expect(
      getRunIdForUserMessage(
        noDirect,
        run({ run_id: "crun_a", user_message_id: "cmsg_1" }),
        run({ run_id: "crun_b", user_message_id: "cmsg_1" }),
      ),
    ).toBe("crun_a");
    expect(
      getRunIdForUserMessage(
        noDirect,
        run({ run_id: "crun_a", user_message_id: "other" }),
        run({ run_id: "crun_b", user_message_id: "cmsg_1" }),
      ),
    ).toBe("crun_b");
    expect(
      getRunIdForUserMessage(
        noDirect,
        run({ run_id: "crun_a", user_message_id: "other" }),
        run({ run_id: "crun_b", user_message_id: "other" }),
      ),
    ).toBeNull();
  });
});
