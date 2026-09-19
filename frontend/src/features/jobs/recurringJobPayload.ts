import type { RecurringJob, RecurringJobUpdate } from "../../api/types";

// Convert a listed recurring job into the raw PUT payload. Ownership metadata
// (agent_source) must survive edits/toggles/deletes of other jobs; the backend
// still decides whether a meaningful edit revokes ownership.
export const toRecurringJobUpdate = (job: RecurringJob): RecurringJobUpdate => {
  const payload: RecurringJobUpdate = {
    id: job.id,
    enabled: job.enabled,
    schedule: job.schedule,
    command: job.command,
  };
  if (job.agent_source) {
    payload.agent_source = job.agent_source;
  }
  return payload;
};

export const toRecurringJobUpdates = (
  jobs: RecurringJob[]
): RecurringJobUpdate[] => jobs.map(toRecurringJobUpdate);
