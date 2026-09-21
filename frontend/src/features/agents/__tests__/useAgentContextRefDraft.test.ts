import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { describe, it, expect, beforeEach } from "vitest";
import {
  buildAgentContextRefDraftKey,
  readAgentContextRefDraft,
  removeAgentContextRefDraft,
  useAgentContextRefDraft,
  writeAgentContextRefDraft,
} from "../useAgentContextRefDraft";
import type { PendingContextRef } from "../agentViewUtils";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function ref(path = "a/b.md"): PendingContextRef {
  return { kind: "vault_file", path };
}

describe("agent context ref draft storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("uses a dedicated key separate from image and prompt drafts", () => {
    expect(buildAgentContextRefDraftKey("asess_1")).toBe("agent-context-refs:asess_1");
    expect(buildAgentContextRefDraftKey("s")).not.toBe("agent-draft:s");
  });

  it("round-trips refs as paths only", () => {
    writeAgentContextRefDraft("asess_1", [ref("a.md"), ref("b/c.md")]);
    const raw = JSON.parse(window.localStorage.getItem("agent-context-refs:asess_1") || "{}");
    expect(raw.refs).toEqual([
      { kind: "vault_file", path: "a.md" },
      { kind: "vault_file", path: "b/c.md" },
    ]);
    expect(readAgentContextRefDraft("asess_1")).toEqual([ref("a.md"), ref("b/c.md")]);
  });

  it("returns [] for missing, corrupt, or invalid drafts", () => {
    expect(readAgentContextRefDraft("missing")).toEqual([]);
    window.localStorage.setItem("agent-context-refs:bad", "{not-json");
    expect(readAgentContextRefDraft("bad")).toEqual([]);
    window.localStorage.setItem(
      "agent-context-refs:invalid",
      JSON.stringify({ refs: [{ kind: "project", path: "a.md" }, { path: "" }] }),
    );
    expect(readAgentContextRefDraft("invalid")).toEqual([]);
  });

  it("removes the key when refs become empty", () => {
    writeAgentContextRefDraft("asess_1", [ref()]);
    writeAgentContextRefDraft("asess_1", []);
    expect(window.localStorage.getItem("agent-context-refs:asess_1")).toBeNull();
    removeAgentContextRefDraft("asess_1");
    expect(readAgentContextRefDraft("asess_1")).toEqual([]);
  });

  it("restores the next session draft on session switch", async () => {
    writeAgentContextRefDraft("asess_A", [ref("a.md")]);
    writeAgentContextRefDraft("asess_B", [ref("b.md")]);
    const { result, rerender } = renderHook(
      ({ sessionId }) => {
        const [refs, setRefs] = useState<PendingContextRef[]>([]);
        const api = useAgentContextRefDraft(sessionId, refs, setRefs);
        return { refs, setRefs, api };
      },
      { initialProps: { sessionId: "asess_A" as string | null } },
    );
    expect(result.current.refs).toEqual([ref("a.md")]);
    // Raw setter schedules a debounced save; switching before it fires must
    // flush the pending refs to the old session's key.
    act(() => {
      result.current.setRefs([ref("a.md"), ref("a2.md")]);
    });
    rerender({ sessionId: "asess_B" });
    await sleep(650);
    expect(result.current.refs).toEqual([ref("b.md")]);
    expect(readAgentContextRefDraft("asess_A")).toEqual([ref("a.md"), ref("a2.md")]);
  });

  it("setLocalContextRefs changes state without scheduling a save", async () => {
    const { result } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => {
        const [refs, setRefs] = useState<PendingContextRef[]>([]);
        const api = useAgentContextRefDraft(sessionId, refs, setRefs);
        return { refs, api };
      },
      { initialProps: { sessionId: "asess_A" as string | null } },
    );
    act(() => {
      result.current.api.setLocalContextRefs([ref("x.md")]);
    });
    expect(result.current.refs).toEqual([ref("x.md")]);
    await sleep(650);
    expect(readAgentContextRefDraft("asess_A")).toEqual([]);
  });
});
