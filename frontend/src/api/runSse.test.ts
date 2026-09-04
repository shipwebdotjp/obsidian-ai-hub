import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  foldTextDeltas,
  loadLastAppliedId,
  parseRunSseBlock,
  saveLastAppliedId,
  storageKey,
  subscribeRunEvents,
} from "./runSse";

describe("runSse", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it("stores only the last applied event id as auxiliary cache", () => {
    const key = storageKey("agent", "arun_1");
    expect(key).toBe("run-sse:agent:arun_1:last-event-id");
    expect(loadLastAppliedId("agent", "arun_1")).toBe(0);
    saveLastAppliedId("agent", "arun_1", 42);
    expect(loadLastAppliedId("agent", "arun_1")).toBe(42);
  });

  it("parses id: + data: blocks and ignores heartbeat comments", () => {
    const seen: { eventId: number; data: Record<string, unknown> }[] = [];
    parseRunSseBlock("id: 7\ndata: {\"type\":\"text_append\",\"delta\":\"hi\"}", (e) =>
      seen.push(e),
    );
    expect(seen).toEqual([{ eventId: 7, data: { type: "text_append", delta: "hi" } }]);
    // Heartbeat has no id/data and must be ignored.
    parseRunSseBlock(": heartbeat", (e) => seen.push(e));
    expect(seen).toHaveLength(1);
  });

  it("folds text_append deltas append-only in id order without duplication", () => {
    const envelopes = [
      { eventId: 2, data: { type: "text_append", delta: "world" } },
      { eventId: 1, data: { type: "text_append", delta: "hello " } },
      { eventId: 2, data: { type: "text_append", delta: "world" } },
    ];
    const { text, lastId } = foldTextDeltas(envelopes.slice(0, 2), 0);
    expect(text).toBe("hello world");
    expect(lastId).toBe(2);
    // Re-delivery of event_id <= lastApplied is ignored.
    const again = foldTextDeltas(envelopes, lastId);
    expect(again.text).toBe("");
    expect(again.lastId).toBe(lastId);
  });

  it("sends Last-Event-ID and stops on terminal without reconnecting", async () => {
    const encoder = new TextEncoder();
    const chunks = [
      'id: 1\ndata: {"type":"text_append","delta":"a"}\n\n',
      'id: 2\ndata: {"type":"done"}\n\n',
    ];
    const stream = new ReadableStream({
      start(controller) {
        for (const c of chunks) controller.enqueue(encoder.encode(c));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: stream,
    });
    vi.stubGlobal("fetch", fetchMock);

    const seen: number[] = [];
    await subscribeRunEvents({
      url: "/api/v1/agent-runs/r1/events",
      lastEventId: 0,
      onEnvelope: (e) => seen.push(e.eventId),
      isTerminal: (e) => String(e.data["type"]) === "done",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("Last-Event-ID")).toBe("0");
    expect(seen).toEqual([1, 2]);
  });

  it("dedups at-least-once redelivery (event_id <= lastApplied ignored)", async () => {
    const encoder = new TextEncoder();
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(
          encoder.encode('id: 1\ndata: {"type":"text_append","delta":"a"}\n\n'),
        );
        // Redelivery of 1 must be ignored by the subscriber.
        controller.enqueue(
          encoder.encode('id: 1\ndata: {"type":"text_append","delta":"a"}\n\n'),
        );
        controller.enqueue(
          encoder.encode('id: 2\ndata: {"type":"done"}\n\n'),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, body: stream }),
    );
    const seen: number[] = [];
    await subscribeRunEvents({
      url: "/x",
      lastEventId: 0,
      onEnvelope: (e) => seen.push(e.eventId),
      isTerminal: (e) => String(e.data["type"]) === "done",
    });
    expect(seen).toEqual([1, 2]);
  });

  it("aborting the subscription does not cancel the run (only stops polling)", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await subscribeRunEvents({
      url: "/x",
      lastEventId: 5,
      signal: controller.signal,
      onEnvelope: () => {},
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
