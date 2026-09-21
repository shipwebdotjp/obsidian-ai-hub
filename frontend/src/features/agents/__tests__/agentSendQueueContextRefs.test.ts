import { describe, it, expect, beforeEach } from "vitest";
import {
  createQueuedMessage,
  readAgentSendQueue,
  writeAgentSendQueue,
} from "../agentSendQueue";

describe("agent send queue context refs", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("round-trips context refs", () => {
    const item = createQueuedMessage({
      content: "see this",
      context_refs: [{ kind: "vault_file", path: "a/b.md" }],
    });
    expect(writeAgentSendQueue("asess_1", [item])).toBe("ok");
    const restored = readAgentSendQueue("asess_1");
    expect(restored[0].context_refs).toEqual([{ kind: "vault_file", path: "a/b.md" }]);
  });

  it("defaults legacy items without context_refs to []", () => {
    window.sessionStorage.setItem(
      "agent-send-queue:asess_1:v1",
      JSON.stringify({
        items: [
          {
            queue_id: "qmsg_1",
            content: "old",
            attachments: [],
            slash_invocation: null,
            idempotency_key: "idem_1",
            created_at: new Date().toISOString(),
            status: "pending",
            error_message: null,
          },
        ],
      }),
    );
    const restored = readAgentSendQueue("asess_1");
    expect(restored).toHaveLength(1);
    expect(restored[0].context_refs).toEqual([]);
  });

  it("drops invalid refs when creating a queued message", () => {
    const item = createQueuedMessage({
      content: "x",
      context_refs: [
        { kind: "vault_file", path: "ok.md" },
        { kind: "project", path: "bad" } as never,
      ],
    });
    expect(item.context_refs).toEqual([{ kind: "vault_file", path: "ok.md" }]);
  });
});
