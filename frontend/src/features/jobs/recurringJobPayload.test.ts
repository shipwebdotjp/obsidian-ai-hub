import { describe, expect, it } from "vitest";

import type { RecurringJob } from "../../api/types";
import {
  toRecurringJobUpdate,
  toRecurringJobUpdates,
} from "./recurringJobPayload";

const baseJob: RecurringJob = {
  id: "agent_job",
  enabled: true,
  schedule: { type: "daily", hour: 9, minute: 0 },
  command: "echo hello",
  is_preset: false,
  next_run: "2026-09-20T00:00:00Z",
  agent_source: {
    agent_id: "agent-1",
    session_id: "sess-1",
    run_id: "run-1",
    registered_at: "2026-09-19T00:00:00+00:00",
  },
};

describe("recurringJobPayload", () => {
  it("keeps agent_source in the PUT payload", () => {
    const payload = toRecurringJobUpdate(baseJob);
    expect(payload.agent_source).toEqual(baseJob.agent_source);
    expect(payload).not.toHaveProperty("is_preset");
    expect(payload).not.toHaveProperty("next_run");
  });

  it("keeps agent_source while toggling enabled on another job", () => {
    const manual: RecurringJob = {
      id: "manual",
      enabled: true,
      schedule: { type: "minutely" },
      command: "echo manual",
      is_preset: false,
    };
    const payloads = toRecurringJobUpdates([
      { ...manual, enabled: false },
      baseJob,
    ]);
    expect(payloads[0]).not.toHaveProperty("agent_source");
    expect(payloads[1].agent_source?.agent_id).toBe("agent-1");
  });
});
