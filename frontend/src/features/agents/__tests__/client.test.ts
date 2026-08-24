import { afterEach, describe, expect, it, vi } from "vitest";
import { streamAgentMessage } from "../../../api/client";
import type { AgentStreamEvent } from "../../../api/types";

function streamFromByteChunks(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("streamAgentMessage", () => {
  it("parses complete SSE events across arbitrary UTF-8 byte and CRLF boundaries", async () => {
    const payload = [
      "data: {\"type\":\"text\",\"delta\":\"こん",
      "にちは\"}\r\n\r\n",
      "data: {\"type\":\"tool_call_detected\",\"call_key\":\"1:0\",\"tool_name\":\"vault_search\",\"iteration\":1}\r\n\r\n",
      "data: {\"type\":\"done\",\r\n",
      "data: \"message\":{\"message_id\":\"m1\",\"session_id\":\"s1\",\"sequence\":2,\"role\":\"assistant\",\"content\":\"こんにちは\",\"created_at\":\"2026-08-24T00:00:00Z\"},\"run\":{\"run_id\":\"r1\",\"session_id\":\"s1\",\"user_message_id\":\"m0\",\"assistant_message_id\":\"m1\",\"status\":\"succeeded\",\"used_tools\":[],\"created_hitl_run_ids\":[],\"error_message\":null,\"started_at\":\"\",\"finished_at\":\"\"},\"hitl_run_ids\":[]}\r\n\r\n",
    ].join("");
    const bytes = new TextEncoder().encode(payload);
    const byteChunks = Array.from(bytes, (byte) => new Uint8Array([byte]));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        status: 200,
        ok: true,
        body: streamFromByteChunks(byteChunks),
      }),
    );

    const events: AgentStreamEvent[] = [];
    await streamAgentMessage("s1", "hello", (event) => events.push(event));

    expect(events).toEqual([
      { type: "text", delta: "こんにちは" },
      {
        type: "tool_call_detected",
        call_key: "1:0",
        tool_name: "vault_search",
        iteration: 1,
      },
      expect.objectContaining({ type: "done" }),
    ]);
  });
});
