import { describe, it, expect, beforeEach } from "vitest";
import {
  CODING_SEND_QUEUE_SIZE_LIMIT,
  buildCodingSendQueueKey,
  clearQueuedCodingMessageError,
  createQueuedCodingMessage,
  enqueueCodingMessage,
  markQueuedCodingMessageError,
  readCodingSendQueue,
  removeCodingSendQueue,
  removeQueuedCodingMessage,
  writeCodingSendQueue,
  type QueuedCodingMessage,
} from "./codingSendQueue";

function queued(
  content = "hello",
  overrides: Partial<QueuedCodingMessage> = {},
): QueuedCodingMessage {
  return {
    ...createQueuedCodingMessage({ content }),
    ...overrides,
  };
}

describe("coding send queue storage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("round-trips queued items in order", () => {
    const first = queued("first");
    const second = queued("second", {
      slash_invocation: { kind: "skill", name: "pdftomd" },
    });
    expect(writeCodingSendQueue("cses_1", [first, second])).toBe("ok");

    const restored = readCodingSendQueue("cses_1");
    expect(restored.map((item) => item.content)).toEqual(["first", "second"]);
    expect(restored[1].slash_invocation).toEqual({ kind: "skill", name: "pdftomd" });
  });

  it("keeps the idempotency key stable across persistence", () => {
    const item = queued("retry me");
    writeCodingSendQueue("cses_1", [item]);
    expect(readCodingSendQueue("cses_1")[0].idempotency_key).toBe(item.idempotency_key);
  });

  it("scopes storage per session", () => {
    writeCodingSendQueue("cses_1", [queued("a")]);
    writeCodingSendQueue("cses_2", [queued("b")]);
    expect(readCodingSendQueue("cses_1").map((i) => i.content)).toEqual(["a"]);
    expect(readCodingSendQueue("cses_2").map((i) => i.content)).toEqual(["b"]);
    removeCodingSendQueue("cses_1");
    expect(readCodingSendQueue("cses_1")).toEqual([]);
    expect(readCodingSendQueue("cses_2")).toHaveLength(1);
  });

  it("returns [] for missing, corrupt, or invalid queues", () => {
    expect(readCodingSendQueue("missing")).toEqual([]);
    window.sessionStorage.setItem(buildCodingSendQueueKey("bad"), "{not-json");
    expect(readCodingSendQueue("bad")).toEqual([]);
    window.sessionStorage.setItem(
      buildCodingSendQueueKey("invalid"),
      JSON.stringify({ version: 1, items: [{ queue_id: "q", content: "x" }] }),
    );
    expect(readCodingSendQueue("invalid")).toEqual([]);
  });

  it("rejects oversized queues without deleting the previous queue", () => {
    writeCodingSendQueue("cses_1", [queued("keep me")]);
    const big = queued("x".repeat(CODING_SEND_QUEUE_SIZE_LIMIT));
    expect(writeCodingSendQueue("cses_1", [big])).toBe("too-large");
    expect(readCodingSendQueue("cses_1").map((i) => i.content)).toEqual(["keep me"]);
  });

  it("removes the key when writing an empty queue", () => {
    writeCodingSendQueue("cses_1", [queued()]);
    expect(writeCodingSendQueue("cses_1", [])).toBe("ok");
    expect(window.sessionStorage.getItem(buildCodingSendQueueKey("cses_1"))).toBeNull();
  });

  it("appends, removes, and toggles error state without reordering", () => {
    const first = queued("first");
    const second = queued("second");
    let items = enqueueCodingMessage([], first);
    items = enqueueCodingMessage(items, second);
    expect(items.map((i) => i.content)).toEqual(["first", "second"]);

    items = markQueuedCodingMessageError(items, first.queue_id, "boom");
    expect(items[0].status).toBe("error");
    expect(items[0].error_message).toBe("boom");
    expect(items[1].status).toBe("pending");

    items = clearQueuedCodingMessageError(items, first.queue_id);
    expect(items[0].status).toBe("pending");

    items = removeQueuedCodingMessage(items, first.queue_id);
    expect(items.map((i) => i.content)).toEqual(["second"]);
  });
});
