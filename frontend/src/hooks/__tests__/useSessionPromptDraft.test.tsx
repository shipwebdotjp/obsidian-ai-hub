import { act, renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import {
  buildPromptDraftKey,
  PROMPT_DRAFT_DEBOUNCE_MS,
  useSessionPromptDraft,
} from "../useSessionPromptDraft";

const DEBOUNCE = PROMPT_DRAFT_DEBOUNCE_MS;
const SETTLE = DEBOUNCE + 150;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

describe("useSessionPromptDraft", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("saves session A draft and does not show it in session B", async () => {
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useSessionPromptDraft("coding", sessionId),
      { initialProps: { sessionId: "sess-A" as string | null } },
    );

    act(() => {
      result.current.setDraft("Aの下書き");
    });
    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-A"))).toBeNull();
    await act(() => sleep(SETTLE));
    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-A"))).toBe(
      "Aの下書き",
    );

    rerender({ sessionId: "sess-B" });
    expect(result.current.draft).toBe("");
  });

  it("restores B draft and then A draft when switching back", async () => {
    window.sessionStorage.setItem(buildPromptDraftKey("coding", "sess-B"), "Bの既存下書き");
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useSessionPromptDraft("coding", sessionId),
      { initialProps: { sessionId: "sess-A" as string | null } },
    );

    act(() => {
      result.current.setDraft("Aの下書き");
    });
    await act(() => sleep(SETTLE));

    rerender({ sessionId: "sess-B" });
    expect(result.current.draft).toBe("Bの既存下書き");

    rerender({ sessionId: "sess-A" });
    expect(result.current.draft).toBe("Aの下書き");
  });

  it("removes the session draft on clearDraft (send success)", async () => {
    const { result } = renderHook(() => useSessionPromptDraft("coding", "sess-A"));
    act(() => {
      result.current.setDraft("送信する内容");
    });
    await act(() => sleep(SETTLE));
    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-A"))).toBe(
      "送信する内容",
    );

    act(() => {
      result.current.setDraft("");
      result.current.clearDraft();
    });
    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-A"))).toBeNull();
    expect(result.current.draft).toBe("");
  });

  it("uses collision-free keys between coding and agents", () => {
    expect(buildPromptDraftKey("coding", "sess-1")).toBe("oaih:prompt-draft:coding:sess-1");
    expect(buildPromptDraftKey("agents", "sess-1")).toBe("oaih:prompt-draft:agents:sess-1");
    expect(buildPromptDraftKey("coding", "sess-1")).not.toBe(
      buildPromptDraftKey("agents", "sess-1"),
    );
  });

  it("flushes pending content to the old session instead of the new one on quick switch", async () => {
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useSessionPromptDraft("coding", sessionId),
      { initialProps: { sessionId: "sess-A" as string | null } },
    );

    // Type in A and switch before the debounce fires.
    act(() => {
      result.current.setDraft("Aの未保存入力");
    });
    rerender({ sessionId: "sess-B" });

    await act(() => sleep(SETTLE));

    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-A"))).toBe(
      "Aの未保存入力",
    );
    expect(window.sessionStorage.getItem(buildPromptDraftKey("coding", "sess-B"))).toBeNull();
    expect(result.current.draft).toBe("");

    // Switch back restores A.
    rerender({ sessionId: "sess-A" });
    expect(result.current.draft).toBe("Aの未保存入力");
  });

  it("saves/removes an explicit session draft immediately", async () => {
    const { result } = renderHook(() => useSessionPromptDraft("coding", "sess-A"));
    const keyA = buildPromptDraftKey("coding", "sess-A");

    act(() => {
      result.current.saveDraftFor("sess-A", "即時保存");
    });
    expect(window.sessionStorage.getItem(keyA)).toBe("即時保存");

    act(() => {
      result.current.removeDraftFor("sess-A");
    });
    expect(window.sessionStorage.getItem(keyA)).toBeNull();

    // No pending timer may resurrect the removed value.
    await act(() => sleep(SETTLE));
    expect(window.sessionStorage.getItem(keyA)).toBeNull();
  });

  it("setLocalDraft changes input without touching storage", async () => {
    const { result } = renderHook(() => useSessionPromptDraft("coding", "sess-A"));
    const keyA = buildPromptDraftKey("coding", "sess-A");

    act(() => {
      result.current.setDraft("入力中");
    });
    act(() => {
      result.current.setLocalDraft("");
    });
    expect(result.current.draft).toBe("");

    // The pending debounced save must have been cancelled.
    await act(() => sleep(SETTLE));
    expect(window.sessionStorage.getItem(keyA)).toBeNull();

    // Restoring locally must not schedule a save either.
    act(() => {
      result.current.setLocalDraft("復元テキスト");
    });
    expect(result.current.draft).toBe("復元テキスト");
    await act(() => sleep(SETTLE));
    expect(window.sessionStorage.getItem(keyA)).toBeNull();
  });

  it("does not break when sessionStorage is unavailable", async () => {
    const original = window.sessionStorage;
    const throwing = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
      clear: () => {},
      key: () => null,
      length: 0,
    } as unknown as Storage;
    Object.defineProperty(window, "sessionStorage", { configurable: true, value: throwing });
    try {
      const { result, unmount } = renderHook(() => useSessionPromptDraft("agents", "sess-X"));
      act(() => {
        result.current.setDraft("入力");
      });
      await act(() => sleep(SETTLE));
      expect(result.current.draft).toBe("入力");
      act(() => {
        result.current.clearDraft();
        result.current.flush();
      });
      unmount();
    } finally {
      Object.defineProperty(window, "sessionStorage", { configurable: true, value: original });
    }
  });
});
