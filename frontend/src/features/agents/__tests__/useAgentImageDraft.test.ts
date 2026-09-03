import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  AGENT_IMAGE_DRAFT_DEBOUNCE_MS,
  buildAgentImageDraftKey,
  readAgentImageDraft,
  removeAgentImageDraft,
  useAgentImageDraft,
  writeAgentImageDraft,
  type ImageDraftItem,
} from "../useAgentImageDraft";

const DEBOUNCE = AGENT_IMAGE_DRAFT_DEBOUNCE_MS;
const SETTLE = DEBOUNCE + 150;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function item(name = "pixel.png"): ImageDraftItem {
  return {
    previewUrl: "data:image/png;base64,QUJD",
    name,
    mime_type: "image/png",
    data: "QUJD",
    size: 3,
  };
}

describe("agent image draft storage", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  it("uses the legacy key format and stays separate from coding keys", () => {
    expect(buildAgentImageDraftKey("asess_456")).toBe("agent-draft:asess_456");
    expect(buildAgentImageDraftKey("s")).not.toBe("oaih:prompt-draft:coding:s");
    expect(buildAgentImageDraftKey("s")).not.toBe("oaih:prompt-draft:agents:s");
  });

  it("round-trips attachments without previewUrl in storage", () => {
    expect(writeAgentImageDraft("asess_456", "hello", [item()])).toBe("ok");
    const raw = JSON.parse(window.localStorage.getItem("agent-draft:asess_456") || "{}");
    expect(raw.text).toBe("hello");
    expect(raw.attachments).toEqual([{ name: "pixel.png", mime_type: "image/png", data: "QUJD", size: 3 }]);
    expect(raw.savedAt).toBeTruthy();

    const restored = readAgentImageDraft("asess_456");
    expect(restored).toEqual([item()]);
  });

  it("returns [] for missing, corrupt, or invalid drafts", () => {
    expect(readAgentImageDraft("missing")).toEqual([]);
    window.localStorage.setItem("agent-draft:bad", "{not-json");
    expect(readAgentImageDraft("bad")).toEqual([]);
    window.localStorage.setItem(
      "agent-draft:invalid",
      JSON.stringify({ text: "x", attachments: [{ name: "n" }], savedAt: "t" }),
    );
    expect(readAgentImageDraft("invalid")).toEqual([]);
  });

  it("rejects oversized drafts and removes the key", () => {
    const big = { ...item(), data: "x".repeat(4_000_001) };
    expect(writeAgentImageDraft("asess_456", "", [big])).toBe("too-large");
    expect(window.localStorage.getItem("agent-draft:asess_456")).toBeNull();
  });

  it("removes the key when attachments are empty", () => {
    writeAgentImageDraft("asess_456", "hello", [item()]);
    expect(writeAgentImageDraft("asess_456", "", [])).toBe("ok");
    expect(window.localStorage.getItem("agent-draft:asess_456")).toBeNull();
  });

  it("does not throw when storage is unavailable", () => {
    const original = window.localStorage;
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
    Object.defineProperty(window, "localStorage", { configurable: true, value: throwing });
    try {
      expect(readAgentImageDraft("asess_456")).toEqual([]);
      expect(writeAgentImageDraft("asess_456", "t", [item()])).toBe("unavailable");
      expect(() => removeAgentImageDraft("asess_456")).not.toThrow();
    } finally {
      Object.defineProperty(window, "localStorage", { configurable: true, value: original });
    }
  });
});

describe("useAgentImageDraft", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  });

  function setup(sessionId: string | null) {
    return renderHook(
      ({ sid }: { sid: string | null }) => {
        const [attachments, setAttachments] = useState<ImageDraftItem[]>([]);
        const api = useAgentImageDraft(sid, attachments, setAttachments, "text", vi.fn());
        return { attachments, setAttachments, api };
      },
      { initialProps: { sid: sessionId } },
    );
  }

  it("saves per session and restores on switch without mixing", async () => {
    const { result, rerender } = setup("sess-A");
    act(() => {
      result.current.setAttachments([item("a.png")]);
    });
    await act(() => sleep(SETTLE));
    expect(readAgentImageDraft("sess-A").map((a) => a.name)).toEqual(["a.png"]);

    rerender({ sid: "sess-B" });
    expect(result.current.attachments).toEqual([]);

    act(() => {
      result.current.setAttachments([item("b.png")]);
    });
    await act(() => sleep(SETTLE));

    rerender({ sid: "sess-A" });
    expect(result.current.attachments.map((a) => a.name)).toEqual(["a.png"]);
    rerender({ sid: "sess-B" });
    expect(result.current.attachments.map((a) => a.name)).toEqual(["b.png"]);
  });

  it("flushes pending images to the old session on quick switch", async () => {
    const { result, rerender } = setup("sess-A");
    act(() => {
      result.current.setAttachments([item("a.png")]);
    });
    rerender({ sid: "sess-B" });
    await act(() => sleep(SETTLE));

    expect(readAgentImageDraft("sess-A").map((a) => a.name)).toEqual(["a.png"]);
    expect(readAgentImageDraft("sess-B")).toEqual([]);
    expect(result.current.attachments).toEqual([]);
  });

  it("setLocalAttachments changes state without scheduling a save", async () => {
    const { result } = setup("sess-A");
    act(() => {
      result.current.setAttachments([item("a.png")]);
    });
    act(() => {
      result.current.api.setLocalAttachments([]);
    });
    expect(result.current.attachments).toEqual([]);
    await act(() => sleep(SETTLE));
    expect(readAgentImageDraft("sess-A")).toEqual([]);
  });
});
