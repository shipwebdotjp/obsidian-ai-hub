import type {
  BatchReviewRequest,
  BatchReviewResponse,
  Memory,
  MemoryDetail,
  MemoryListResponse,
  EditPayload,
  DeleteResponse,
  BatchDeleteRequest,
  BatchDeleteResponse,
  ResearchListResponse,
  ResearchTheme,
  ResearchJob,
  ResearchRunAcceptedResponse,
  VaultSearchResponse,
  VaultFileResponse,
  SummaryDetail,
  SummaryGenerateRequest,
  SummaryUpdatePayload,
  SummaryDeleteResponse,
  EditOptionsResponse,
  Person,
  PlannerGenerateResponse,
  PlannerProposal,
  PlannerProposalListResponse,
  PlannerProposalUpdatePayload,
  PlannerTimelineResponse,
  Agent,
  AgentTool,
  AgentSession,
  AgentMessage,
  AgentRun,
  AgentSessionDetailResponse,
  AgentStreamEvent,
  HealthcareOverviewResponse,
  HealthcareCorrelationResponse,
} from "./types";

const TOKEN_KEY = "obsidian-ai-hub:api-token";

// TODO: migrate to httpOnly cookie once backend supports cookie-based auth
// to prevent token exfiltration via XSS.

export const AUTH_EXPIRED_EVENT = "auth:expired";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, message: string, body: any = null) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  headers.set("Accept", "application/json");
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401) {
    clearToken();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    throw new ApiError(401, "Authentication failed. Please check your token.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    let body: any = null;
    try {
      body = await res.json();
      if (body && body.detail) {
        if (typeof body.detail === "string") {
          detail = body.detail;
        } else if (typeof body.detail === "object" && body.detail.message) {
          detail = body.detail.message;
        }
      }
    } catch (_) {
      // ignore
    }
    throw new ApiError(res.status, detail, body);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export function listMemories(params: {
  status?: string;
  kind?: string;
  topic?: string;
  q?: string;
}): Promise<MemoryListResponse> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) sp.set(k, v);
  }
  const qs = sp.toString();
  return request<MemoryListResponse>(`/api/v1/memories${qs ? `?${qs}` : ""}`);
}

export function getMemory(memoryId: string): Promise<MemoryDetail> {
  return request<MemoryDetail>(`/api/v1/memories/${encodeURIComponent(memoryId)}`);
}

export function reviewMemory(
  memoryId: string,
  action: "approve" | "reject" | "edit",
  newContent?: string,
): Promise<{ memory: Memory }> {
  return request<{ memory: Memory }>(
    `/api/v1/memories/${encodeURIComponent(memoryId)}/review`,
    {
      method: "POST",
      body: JSON.stringify({ action, new_content: newContent }),
    },
  );
}


export function resolveMemory(
  memoryId: string,
  action: "keep_both" | "replace_existing" | "merge_existing" | "supersede_existing",
  targetMemoryId: string,
  integratedContent?: string,
  switchDate?: string,
): Promise<{ candidate: Memory; target?: Memory }> {
  return request<{ candidate: Memory; target?: Memory }>(
    `/api/v1/memories/${encodeURIComponent(memoryId)}/resolve`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        target_memory_id: targetMemoryId,
        integrated_content: integratedContent,
        switch_date: switchDate,
      }),
    },
  );
}

export function editMemory(
  memoryId: string,
  payload: EditPayload,
): Promise<{ found: boolean; updated: boolean; changes: Record<string, unknown>; memory: Memory }> {
  return request(`/api/v1/memories/${encodeURIComponent(memoryId)}/edit`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function batchReview(body: BatchReviewRequest): Promise<BatchReviewResponse> {
  return request<BatchReviewResponse>("/api/v1/memories/batch-review", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- HITL client functions ---

import type {
  HitlRunDetail,
  HitlRunListResponse,
} from "./types";

export function listHitlRuns(params: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<HitlRunListResponse> {
  const sp = new URLSearchParams();
  if (params.status) sp.set("status", params.status);
  if (params.limit) sp.set("limit", String(params.limit));
  if (params.offset) sp.set("offset", String(params.offset));
  const qs = sp.toString();
  return request<HitlRunListResponse>(`/api/v1/hitl/runs${qs ? `?${qs}` : ""}`);
}

export function getHitlRun(runId: string): Promise<HitlRunDetail> {
  return request<HitlRunDetail>(`/api/v1/hitl/runs/${encodeURIComponent(runId)}`);
}

export function submitHitlAnswer(
  runId: string,
  questionKey: string,
  answer: any,
  comment?: string | null,
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `/api/v1/hitl/runs/${encodeURIComponent(runId)}/questions/${encodeURIComponent(questionKey)}/answer`,
    {
      method: "POST",
      body: JSON.stringify({ answer, comment }),
    },
  );
}

export function cancelHitlRun(runId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `/api/v1/hitl/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

// --- Task Config APIs ---

import type {
  TaskConfigResponse,
  TaskConfigUpdateResponse,
  CommandPreviewResponse,
} from "./types";

export function getTaskConfig(): Promise<TaskConfigResponse> {
  return request<TaskConfigResponse>("/api/v1/task-config");
}

export function updateTaskConfig(revision: string, tasks: any[]): Promise<TaskConfigUpdateResponse> {
  return request<TaskConfigUpdateResponse>("/api/v1/task-config", {
    method: "PUT",
    body: JSON.stringify({ revision, tasks }),
  });
}

export function previewCommand(command: string): Promise<CommandPreviewResponse> {
  return request<CommandPreviewResponse>("/api/v1/task-config/preview", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

export function apiPatch<T>(path: string, body: any): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, {
    method: "DELETE",
  });
}

export function deleteMemory(memoryId: string): Promise<DeleteResponse> {
  return request<DeleteResponse>(
    `/api/v1/memories/${encodeURIComponent(memoryId)}`,
    { method: "DELETE" },
  );
}

export function batchDeleteMemories(body: BatchDeleteRequest): Promise<BatchDeleteResponse> {
  return request<BatchDeleteResponse>("/api/v1/memories/batch-delete", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function health(): Promise<{
  status: string;
  auth_required: boolean;
}> {
  return request("/health");
}

export function getMemoryOptions(): Promise<{ kinds: string[]; topics: string[] }> {
  return request<{ kinds: string[]; topics: string[] }>("/api/v1/memory-options");
}

export function renderCopilotProfile(): Promise<{ updated_files: string[] }> {
  return request<{ updated_files: string[] }>("/api/v1/copilot-profile/render", {
    method: "POST",
  });
}

// Research Theme API

export function listResearchThemes(params: {
  status?: string;
  job_status?: string;
  q?: string;
}): Promise<ResearchListResponse> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) sp.set(k, v);
  }
  const qs = sp.toString();
  return request<ResearchListResponse>(`/api/v1/research-themes${qs ? `?${qs}` : ""}`);
}

export function getResearchTheme(themeId: string): Promise<ResearchTheme> {
  return request<ResearchTheme>(`/api/v1/research-themes/${encodeURIComponent(themeId)}`);
}

export function rerunResearchTheme(themeId: string): Promise<ResearchJob> {
  return request<ResearchJob>(
    `/api/v1/research-themes/${encodeURIComponent(themeId)}/rerun`,
    { method: "POST" },
  );
}

export function runResearchTheme(
  theme: string,
  mode: "auto" | "internal" | "web" | "deep",
): Promise<ResearchRunAcceptedResponse> {
  return request<ResearchRunAcceptedResponse>("/api/v1/research-themes/run", {
    method: "POST",
    body: JSON.stringify({ theme, mode }),
  });
}

// Vault Search API

export function searchVault(params: {
  q: string;
  k?: number;
  mode?: "hybrid" | "keyword" | "similarity";
}): Promise<VaultSearchResponse> {
  const sp = new URLSearchParams();
  sp.set("q", params.q);
  if (params.k) sp.set("k", String(params.k));
  if (params.mode) sp.set("mode", params.mode);
  return request<VaultSearchResponse>(`/api/v1/vault-search?${sp.toString()}`);
}

export function getVaultFile(path: string, signal?: AbortSignal): Promise<VaultFileResponse> {
  const sp = new URLSearchParams();
  sp.set("path", path);
  return request<VaultFileResponse>(`/api/v1/vault-file?${sp.toString()}`, { signal });
}

// Summary Dashboard API

import type {
  DashboardHomeResponse,
  DashboardBrowseResponse,
  DashboardDayDetailsResponse,
  DashboardStatsResponse,
} from "./types";

export function getDashboardHome(): Promise<DashboardHomeResponse> {
  return request<DashboardHomeResponse>("/api/v1/summary-dashboard/home");
}

export function getDashboardBrowse(params: {
  year?: string;
  month?: string;
}): Promise<DashboardBrowseResponse> {
  const sp = new URLSearchParams();
  if (params.year) sp.set("year", params.year);
  if (params.month) sp.set("month", params.month);
  const qs = sp.toString();
  return request<DashboardBrowseResponse>(
    `/api/v1/summary-dashboard/browse${qs ? `?${qs}` : ""}`
  );
}

export function getDashboardSummary(summaryId: string): Promise<SummaryDetail> {
  return request<SummaryDetail>(
    `/api/v1/summary-dashboard/summaries/${encodeURIComponent(summaryId)}`
  );
}

export function generateSummary(payload: SummaryGenerateRequest): Promise<SummaryDetail> {
  return request<SummaryDetail>("/api/v1/summary-dashboard/summaries/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getDashboardDayDetails(targetDate: string): Promise<DashboardDayDetailsResponse> {
  return request<DashboardDayDetailsResponse>(
    `/api/v1/summary-dashboard/days/${encodeURIComponent(targetDate)}`
  );
}

export function getDashboardStats(params: {
  start_date: string;
  end_date: string;
}): Promise<DashboardStatsResponse> {
  const sp = new URLSearchParams();
  sp.set("start_date", params.start_date);
  sp.set("end_date", params.end_date);
  return request<DashboardStatsResponse>(
    `/api/v1/summary-dashboard/stats?${sp.toString()}`
  );
}

export function getEditOptions(): Promise<EditOptionsResponse> {
  return request<EditOptionsResponse>("/api/v1/summary-dashboard/edit-options");
}

export function updateSummary(
  summaryId: string,
  payload: SummaryUpdatePayload,
): Promise<SummaryDetail> {
  return request<SummaryDetail>(
    `/api/v1/summary-dashboard/summaries/${encodeURIComponent(summaryId)}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function deleteSummary(
  summaryId: string,
): Promise<SummaryDeleteResponse> {
  return request<SummaryDeleteResponse>(
    `/api/v1/summary-dashboard/summaries/${encodeURIComponent(summaryId)}`,
    { method: "DELETE" },
  );
}

export function getHealthcareOverview(params: {
  start_date: string;
  end_date: string;
}): Promise<HealthcareOverviewResponse> {
  const sp = new URLSearchParams();
  sp.set("start_date", params.start_date);
  sp.set("end_date", params.end_date);
  return request<HealthcareOverviewResponse>(
    `/api/v1/healthcare/overview?${sp.toString()}`,
  );
}

export function getHealthcareCorrelation(params: {
  metric_x: string;
  metric_y: string;
  start_date: string;
  end_date: string;
}): Promise<HealthcareCorrelationResponse> {
  const sp = new URLSearchParams();
  sp.set("metric_x", params.metric_x);
  sp.set("metric_y", params.metric_y);
  sp.set("start_date", params.start_date);
  sp.set("end_date", params.end_date);
  return request<HealthcareCorrelationResponse>(
    `/api/v1/healthcare/correlation?${sp.toString()}`,
  );
}

export function listPeople(): Promise<Person[]> {
  return request<Person[]>("/api/v1/people");
}

export function getPlannerTimeline(start: string, end: string): Promise<PlannerTimelineResponse> {
  const qs = new URLSearchParams({ start, end }).toString();
  return request<PlannerTimelineResponse>(`/api/v1/planner/timeline?${qs}`);
}

export function listPlannerProposals(params: {
  status?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}): Promise<PlannerProposalListResponse> {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const qs = sp.toString();
  return request<PlannerProposalListResponse>(
    `/api/v1/planner/proposals${qs ? `?${qs}` : ""}`,
  );
}

export function getPlannerProposal(proposalId: string): Promise<PlannerProposal> {
  return request<PlannerProposal>(
    `/api/v1/planner/proposals/${encodeURIComponent(proposalId)}`,
  );
}

export function updatePlannerProposal(
  proposalId: string,
  payload: PlannerProposalUpdatePayload,
): Promise<PlannerProposal> {
  return request<PlannerProposal>(
    `/api/v1/planner/proposals/${encodeURIComponent(proposalId)}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function rejectPlannerProposal(proposalId: string): Promise<PlannerProposal> {
  return request<PlannerProposal>(
    `/api/v1/planner/proposals/${encodeURIComponent(proposalId)}/reject`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export function promotePlannerProposal(proposalId: string): Promise<PlannerProposal> {
  return request<PlannerProposal>(
    `/api/v1/planner/proposals/${encodeURIComponent(proposalId)}/promote`,
    { method: "POST" },
  );
}

export function generatePlannerProposals(): Promise<PlannerGenerateResponse> {
  return request<PlannerGenerateResponse>("/api/v1/planner/generate", {
    method: "POST",
  });
}

// --- AI Agent APIs ---

export function listAgents(): Promise<{ agents: Agent[] }> {
  return request<{ agents: Agent[] }>("/api/v1/agents");
}

export function createAgent(payload: {
  name: string;
  system_prompt: string;
  tool_ids?: string[];
  provider?: string;
  model?: string;
}): Promise<{ agent: Agent }> {
  return request<{ agent: Agent }>("/api/v1/agents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAgent(agentId: string): Promise<{ agent: Agent }> {
  return request<{ agent: Agent }>(`/api/v1/agents/${encodeURIComponent(agentId)}`);
}

export function updateAgent(
  agentId: string,
  payload: {
    name?: string;
    system_prompt?: string;
    tool_ids?: string[];
    provider?: string;
    model?: string;
  },
): Promise<{ agent: Agent }> {
  return request<{ agent: Agent }>(`/api/v1/agents/${encodeURIComponent(agentId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function deleteAgent(agentId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(`/api/v1/agents/${encodeURIComponent(agentId)}`, {
    method: "DELETE",
  });
}

export function listAgentTools(): Promise<{ tools: AgentTool[] }> {
  return request<{ tools: AgentTool[] }>("/api/v1/agent-tools");
}

export function listAgentSessions(agentId: string): Promise<{ sessions: AgentSession[] }> {
  return request<{ sessions: AgentSession[] }>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/sessions`,
  );
}

export function createAgentSession(
  agentId: string,
  payload?: { title?: string },
): Promise<{ session: AgentSession }> {
  return request<{ session: AgentSession }>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/sessions`,
    {
      method: "POST",
      body: JSON.stringify(payload || {}),
    },
  );
}

export function getAgentSessionDetail(
  sessionId: string,
): Promise<AgentSessionDetailResponse> {
  return request<AgentSessionDetailResponse>(
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function deleteAgentSession(sessionId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

/** Parse one complete SSE event block, including CRLF and multiline data. */
export function parseAgentSseEvent(
  eventBlock: string,
  onEvent: (event: AgentStreamEvent) => void,
): void {
  const dataLines: string[] = [];
  for (const line of eventBlock.split(/\r?\n/)) {
    if (line.startsWith(":")) continue;
    if (!line.startsWith("data:")) continue;

    let data = line.slice(5);
    if (data.startsWith(" ")) data = data.slice(1);
    dataLines.push(data);
  }

  if (dataLines.length === 0) return;

  const jsonStr = dataLines.join("\n");
  try {
    const parsed = JSON.parse(jsonStr) as AgentStreamEvent;
    onEvent(parsed);
  } catch (e) {
    console.error("Failed to parse SSE event:", jsonStr, e);
  }
}

function drainAgentSseEvents(
  buffer: string,
  onEvent: (event: AgentStreamEvent) => void,
): string {
  let remainder = buffer;
  while (true) {
    const separator = /\r?\n\r?\n/.exec(remainder);
    if (!separator || separator.index === undefined) return remainder;

    parseAgentSseEvent(remainder.slice(0, separator.index), onEvent);
    remainder = remainder.slice(separator.index + separator[0].length);
  }
}

export async function streamAgentMessage(
  sessionId: string,
  content: string,
  onEvent: (event: AgentStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  headers.set("Accept", "text/event-stream");
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}/messages/stream`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({ content }),
      signal,
    },
  );

  if (response.status === 401) {
    clearToken();
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    throw new ApiError(401, "Authentication failed.");
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errJson = await response.json();
      if (errJson && errJson.detail) detail = errJson.detail;
    } catch (_) {}
    throw new ApiError(response.status, detail);
  }

  if (!response.body) {
    throw new Error("ReadableStream not supported by response body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = drainAgentSseEvents(buffer, onEvent);
  }

  // Flush an incomplete UTF-8 sequence retained by TextDecoder, then parse
  // the final event even when a proxy omitted its trailing blank line.
  buffer += decoder.decode();
  buffer = drainAgentSseEvents(buffer, onEvent);
  if (buffer.trim()) {
    parseAgentSseEvent(buffer, onEvent);
  }
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function apiPost<T>(path: string, body: any): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
