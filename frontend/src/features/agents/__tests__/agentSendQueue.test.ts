import { describe, it, expect, beforeEach } from "vitest";
import {
  AGENT_SEND_QUEUE_SIZE_LIMIT,
  buildAgentSendQueueKey,
  clearQueuedAgentMessageError,
  createQueuedMessage,
  enqueueAgentMessage,
  markQueuedAgentMessageError,
  readAgentSendQueue,
  removeAgentSendQueue,
  removeQueuedAgentMessage,
  writeAgentSendQueue,
  type QueuedAgentMessage,
} from "../agentSendQueue";

function queued(content = "hello", overrides: Partial<QueuedAgentMessage> = {}): QueuedAgentMessage {
  return {
    ...createQueuedMessage({ content }),
    ...overrides,
  };
}

describe("agent send queue storage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("round-trips queued items in order", () => {
    const first = queued("first");
    const second = queued("second", {
      attachments: [{ name: "p.png", mime_type: "image/png", data: "QUJD" }],
      slash_invocation: { kind: "skill", name: "search" },
    });
    expect(writeAgentSendQueue("asess_1", [first, second])).toBe("ok");

    const restored = readAgentSendQueue("asess_1");
    expect(restored.map((item) => item.content)).toEqual(["first", "second"]);
    expect(restored[1].attachments).toEqual([
      { name: "p.png", mime_type: "image/png", data: "QUJD" },
    ]);
    expect(restored[1].slash_invocation).toEqual({ kind: "skill", name: "search" });
  });

  it("keeps the idempotency key stable across persistence", () => {
    const item = queued("retry me");
    writeAgentSendQueue("asess_1", [item]);
    const restored = readAgentSendQueue("asess_1");
    expect(restored[0].idempotency_key).toBe(item.idempotency_key);
  });

  it("scopes storage per session", () => {
    writeAgentSendQueue("asess_1", [queued("a")]);
    writeAgentSendQueue("asess_2", [queued("b")]);
    expect(readAgentSendQueue("asess_1").map((i) => i.content)).toEqual(["a"]);
    expect(readAgentSendQueue("asess_2").map((i) => i.content)).toEqual(["b"]);
    removeAgentSendQueue("asess_1");
    expect(readAgentSendQueue("asess_1")).toEqual([]);
    expect(readAgentSendQueue("asess_2")).toHaveLength(1);
  });

  it("returns [] for missing, corrupt, or invalid queues", () => {
    expect(readAgentSendQueue("missing")).toEqual([]);
    window.sessionStorage.setItem(buildAgentSendQueueKey("bad"), "{not-json");
    expect(readAgentSendQueue("bad")).toEqual([]);
    window.sessionStorage.setItem(
      buildAgentSendQueueKey("invalid"),
      JSON.stringify({ version: 1, items: [{ queue_id: "q", content: "x" }] }),
    );
    expect(readAgentSendQueue("invalid")).toEqual([]);
  });

  it("rejects oversized queues without deleting the previous queue", () => {
    writeAgentSendQueue("asess_1", [queued("keep me")]);
    const big = queued("x", {
      attachments: [{ name: "big.png", mime_type: "image/png", data: "y".repeat(AGENT_SEND_QUEUE_SIZE_LIMIT) }],
    });
    expect(writeAgentSendQueue("asess_1", [big])).toBe("too-large");
    expect(readAgentSendQueue("asess_1").map((i) => i.content)).toEqual(["keep me"]);
  });

  it("removes the key when writing an empty queue", () => {
    writeAgentSendQueue("asess_1", [queued()]);
    expect(writeAgentSendQueue("asess_1", [])).toBe("ok");
    expect(window.sessionStorage.getItem(buildAgentSendQueueKey("asess_1"))).toBeNull();
  });

  it("appends, removes, and toggles error state without reordering", () => {
    const first = queued("first");
    const second = queued("second");
    let items = enqueueAgentMessage([], first);
    items = enqueueAgentMessage(items, second);
    expect(items.map((i) => i.content)).toEqual(["first", "second"]);

    items = markQueuedAgentMessageError(items, first.queue_id, "boom");
    expect(items[0].status).toBe("error");
    expect(items[0].error_message).toBe("boom");
    expect(items[1].status).toBe("pending");

    items = clearQueuedAgentMessageError(items, first.queue_id);
    expect(items[0].status).toBe("pending");

    items = removeQueuedAgentMessage(items, first.queue_id);
    expect(items.map((i) => i.content)).toEqual(["second"]);
  });
});
