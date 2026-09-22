import type { RecurringJob, RecurringJobUpdate } from "../../api/types";

// Convert a listed recurring job into the raw PUT payload. Ownership metadata
// (agent_source) must survive edits/toggles/deletes of other jobs; the backend
// still decides whether a meaningful edit revokes ownership.
export const toRecurringJobUpdate = (job: RecurringJob): RecurringJobUpdate => {
  const payload: RecurringJobUpdate = {
    id: job.id,
    enabled: job.enabled,
    schedule: job.schedule,
  };
  // command and workflow are exclusive targets; send only the one in use so a
  // workflow job's payload never carries a stale command (and vice versa).
  if (job.workflow) {
    payload.workflow = {
      workflow_id: job.workflow.workflow_id,
      inputs: job.workflow.inputs ?? {},
    };
  } else {
    payload.command = job.command ?? "";
  }
  if (job.agent_source) {
    payload.agent_source = job.agent_source;
  }
  return payload;
};

export const toRecurringJobUpdates = (
  jobs: RecurringJob[]
): RecurringJobUpdate[] => jobs.map(toRecurringJobUpdate);
