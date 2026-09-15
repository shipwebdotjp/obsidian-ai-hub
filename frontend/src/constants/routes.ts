export const ROUTES = {
  MEMORIES: "/memories",
  RESEARCH: "/research",
  AGENTS: "/agents",
  CODING: "/coding",
  VAULT_SEARCH: "/vault-search",
  SUMMARY_DASHBOARD: "/summary-dashboard",
  HEALTHCARE: "/healthcare",
  PEOPLE: "/people",
  PROJECTS: "/projects",
  TASKS: "/tasks",
  EXECUTION_LOGS: "/execution-logs",
  EXECUTION_LOGS_LOGS: "/execution-logs/logs",
  EXECUTION_LOGS_TASK_STATES: "/execution-logs/task-states",
  HITL: "/hitl",
  TASK_AGENT: "/task-agent",
  TASK_AGENT_DETAIL: "/task-agent/:taskId",
  TASK_AGENT_CAPABILITIES: "/task-agent/capabilities",
  PLANNER: "/planner",
  SETTINGS: "/settings",
} as const;

export function taskAgentDetailPath(taskId: string): string {
  return `/task-agent/${encodeURIComponent(taskId)}`;
}
