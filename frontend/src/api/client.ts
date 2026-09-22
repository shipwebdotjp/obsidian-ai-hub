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
  ResearchMode,
  ResearchRunAcceptedResponse,
  VaultSearchResponse,
  VaultFileResponse,
  VaultFilesResponse,
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
  PlannerRejectPayload,
  PlannerTimelineResponse,
  Agent,
  AgentTool,
  AgentSession,
  AgentMessageSearchResult,
  AgentMessage,
  AgentMessageAttachment,
  AgentContextRef,
  AgentRun,
  AgentSessionDetailResponse,
  HealthcareOverviewResponse,
  HealthcareCorrelationResponse,
  HealthcareImportResponse,
  AgentPromptTemplate,
  SlashInvocation,
  AgentSlashCandidatesResponse,
  SchedulerJobConfigResponse,
  SchedulerJobConfigUpdateResponse,
  SchedulableWorkflowListResponse,
  CommandPreviewResponse,
  OneShotJobListResponse,
  OneShotJobDetail,
  OneShotJobSummary,
  RecurringJobUpdate,
  JobState,
  WorkflowCapabilityListResponse,
  WorkflowDetail,
  WorkflowEdge,
  WorkflowListResponse,
  WorkflowNode,
  WorkflowRevision,
  WorkflowRun,
  WorkflowTemplateListResponse,
  WorkflowValidationResponse,
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

/** クエリ文字列を構築する。`undefined` / `null` / 空文字は除外する。 */
export function buildQuery(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    sp.set(key, String(value));
  }
  return sp.toString();
}

/** パスにクエリ文字列を付与する。クエリが空ならパスのみを返す。 */
export function withQuery(path: string, params: Record<string, unknown> = {}): string {
  const qs = buildQuery(params);
  return qs ? `${path}?${qs}` : path;
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
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
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
  person_id?: string;
  limit?: number;
  offset?: number;
}): Promise<MemoryListResponse> {
  return request<MemoryListResponse>(withQuery("/api/v1/memories", params));
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

export function apiPut<T>(path: string, body: any): Promise<T> {
  return request<T>(path, {
    method: "PUT",
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
  return request<HitlRunListResponse>(
    withQuery("/api/v1/hitl/runs", {
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    }),
  );
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

// --- Scheduler Job APIs ---

export function getRecurringJobs(): Promise<SchedulerJobConfigResponse> {
  return request<SchedulerJobConfigResponse>("/api/v1/scheduler-jobs/recurring-jobs");
}

export function updateRecurringJobs(revision: string, jobs: RecurringJobUpdate[]): Promise<SchedulerJobConfigUpdateResponse> {
  return request<SchedulerJobConfigUpdateResponse>("/api/v1/scheduler-jobs/recurring-jobs", {
    method: "PUT",
    body: JSON.stringify({ revision, jobs }),
  });
}

export function previewCommand(command: string): Promise<CommandPreviewResponse> {
  return request<CommandPreviewResponse>("/api/v1/scheduler-jobs/preview", {
    method: "POST",
    body: JSON.stringify({ command }),
  });
}

export function listOneShotJobs(limit = 100, offset = 0): Promise<OneShotJobListResponse> {
  const safeLimit = Number.isFinite(limit) ? Math.min(200, Math.max(1, Math.floor(limit))) : 100;
  const safeOffset = Number.isFinite(offset) ? Math.max(0, Math.floor(offset)) : 0;
  return request<OneShotJobListResponse>(
    withQuery("/api/v1/scheduler-jobs/one-shot-jobs", {
      limit: safeLimit,
      offset: safeOffset,
    }),
  );
}

export function getSchedulableWorkflows(): Promise<SchedulableWorkflowListResponse> {
  return request<SchedulableWorkflowListResponse>("/api/v1/workflows/schedulable");
}

export function createOneShotWorkflowJob(
  workflowId: string,
  inputs: Record<string, unknown>,
  runAt?: string | null,
): Promise<OneShotJobSummary> {
  return request<OneShotJobSummary>("/api/v1/scheduler-jobs/one-shot-jobs", {
    method: "POST",
    body: JSON.stringify({ workflow_id: workflowId, inputs, run_at: runAt ?? null }),
  });
}

export function getOneShotJobDetail(jobId: string): Promise<OneShotJobDetail> {
  return request<OneShotJobDetail>(
    `/api/v1/scheduler-jobs/one-shot-jobs/${encodeURIComponent(jobId)}`,
  );
}

export function cancelOneShotJob(jobId: string): Promise<OneShotJobSummary> {
  return request<OneShotJobSummary>(
    `/api/v1/scheduler-jobs/one-shot-jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: "POST" },
  );
}

export function listJobStates(): Promise<{ items: JobState[] }> {
  return request<{ items: JobState[] }>("/api/v1/scheduler-jobs/job-states");
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
  return request<ResearchListResponse>(withQuery("/api/v1/research-themes", params));
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
  mode: ResearchMode,
  projectId?: number,
): Promise<ResearchRunAcceptedResponse> {
  const body: Record<string, unknown> = { theme, mode };
  if (projectId != null) body.project_id = projectId;
  return request<ResearchRunAcceptedResponse>("/api/v1/research-themes/run", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// Vault Search API

export function searchVault(params: {
  q: string;
  k?: number;
  mode?: "hybrid" | "keyword" | "similarity";
}, signal?: AbortSignal): Promise<VaultSearchResponse> {
  return request<VaultSearchResponse>(withQuery("/api/v1/vault-search", params), { signal });
}

export function getVaultFile(path: string, signal?: AbortSignal): Promise<VaultFileResponse> {
  return request<VaultFileResponse>(withQuery("/api/v1/vault-file", { path }), { signal });
}

export function listVaultFiles(signal?: AbortSignal): Promise<VaultFilesResponse> {
  return request<VaultFilesResponse>("/api/v1/vault-files", { signal });
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
  return request<DashboardBrowseResponse>(
    withQuery("/api/v1/summary-dashboard/browse", params)
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
  return request<DashboardStatsResponse>(
    withQuery("/api/v1/summary-dashboard/stats", params)
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
  return request<HealthcareOverviewResponse>(
    withQuery("/api/v1/healthcare/overview", params),
  );
}

export function getHealthcareCorrelation(params: {
  metric_x: string;
  metric_y: string;
  start_date: string;
  end_date: string;
}): Promise<HealthcareCorrelationResponse> {
  return request<HealthcareCorrelationResponse>(
    withQuery("/api/v1/healthcare/correlation", params),
  );
}

export function importHealthcareZip(input: {
  file?: File;
  path?: string;
}): Promise<HealthcareImportResponse> {
  const form = new FormData();
  if (input.file) {
    form.append("file", input.file);
  } else if (input.path && input.path.trim()) {
    form.append("path", input.path.trim());
  } else {
    throw new Error("file or path is required");
  }
  return request<HealthcareImportResponse>("/api/v1/healthcare/import", {
    method: "POST",
    body: form,
  });
}

export function listPeople(): Promise<Person[]> {
  return request<Person[]>("/api/v1/people");
}

export function getPlannerTimeline(start: string, end: string): Promise<PlannerTimelineResponse> {
  return request<PlannerTimelineResponse>(
    withQuery("/api/v1/planner/timeline", { start, end }),
  );
}

export function listPlannerProposals(params: {
  status?: string;
  kind?: string;
  limit?: number;
  offset?: number;
}): Promise<PlannerProposalListResponse> {
  return request<PlannerProposalListResponse>(
    withQuery("/api/v1/planner/proposals", params),
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

export function rejectPlannerProposal(
  proposalId: string,
  payload: PlannerRejectPayload = {},
): Promise<PlannerProposal> {
  return request<PlannerProposal>(
    `/api/v1/planner/proposals/${encodeURIComponent(proposalId)}/reject`,
    { method: "POST", body: JSON.stringify(payload) },
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
  delegate_agent_ids?: string[];
  provider?: string;
  model?: string;
  advanced_params?: { max_tokens?: number; reasoning?: { effort?: string } } | null;
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
    delegate_agent_ids?: string[];
    provider?: string;
    model?: string;
    advanced_params?: { max_tokens?: number; reasoning?: { effort?: string } } | null;
    pinned?: boolean;
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

export function searchAgentMessages(
  query: string,
): Promise<{ results: AgentMessageSearchResult[] }> {
  return request<{ results: AgentMessageSearchResult[] }>(
    withQuery("/api/v1/agent-sessions/search", { q: query }),
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

export function updateAgentSession(
  sessionId: string,
  payload: { title?: string; pinned?: boolean },
): Promise<{ session: AgentSession }> {
  return request<{ session: AgentSession }>(
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function getAgentSlashCandidates(
  sessionId: string,
): Promise<AgentSlashCandidatesResponse> {
  return request<AgentSlashCandidatesResponse>(
    `/api/v1/agent-sessions/${encodeURIComponent(sessionId)}/slash-candidates`,
  );
}

export function listPromptTemplates(agentId: string): Promise<{ templates: AgentPromptTemplate[] }> {
  return request<{ templates: AgentPromptTemplate[] }>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/prompt-templates`,
  );
}

export function createPromptTemplate(
  agentId: string,
  payload: { name: string; content: string },
): Promise<{ template: AgentPromptTemplate }> {
  return request<{ template: AgentPromptTemplate }>(
    `/api/v1/agents/${encodeURIComponent(agentId)}/prompt-templates`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getPromptTemplate(templateId: string): Promise<{ template: AgentPromptTemplate }> {
  return request<{ template: AgentPromptTemplate }>(
    `/api/v1/agent-prompt-templates/${encodeURIComponent(templateId)}`,
  );
}

export function updatePromptTemplate(
  templateId: string,
  payload: { name?: string; content?: string; display_order?: number },
): Promise<{ template: AgentPromptTemplate }> {
  return request<{ template: AgentPromptTemplate }>(
    `/api/v1/agent-prompt-templates/${encodeURIComponent(templateId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function deletePromptTemplate(templateId: string): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `/api/v1/agent-prompt-templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
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

// --- Reconnectable Run APIs (docs/run-sse) ---

export function startAgentRun(
  sessionId: string,
  payload: {
    content: string;
    images?: AgentMessageAttachment[];
    slash_invocation?: SlashInvocation | null;
    context_refs?: AgentContextRef[];
  },
  idempotencyKey?: string,
): Promise<{ run: AgentRun }> {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  const body: Record<string, unknown> = { content: payload.content };
  if (payload.images && payload.images.length > 0) {
    body.images = payload.images.map((att) => ({
      name: att.name,
      mime_type: att.mime_type,
      data: att.data,
    }));
  }
  if (payload.slash_invocation) {
    body.slash_invocation = payload.slash_invocation;
  }
  if (payload.context_refs && payload.context_refs.length > 0) {
    body.context_refs = payload.context_refs.map((ref) => ({
      kind: ref.kind,
      path: ref.path,
    }));
  }
  return fetch(`/api/v1/agent-sessions/${encodeURIComponent(sessionId)}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  }).then(async (res) => {
    if (res.status === 401) {
      clearToken();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
      throw new ApiError(401, "Authentication failed.");
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const errJson = await res.json();
        if (errJson?.detail) detail = errJson.detail;
      } catch {}
      throw new ApiError(res.status, detail);
    }
    return (await res.json()) as { run: import("./types").AgentRun };
  });
}

export function cancelAgentRun(
  runId: string,
): Promise<{ run: import("./types").AgentRun }> {
  return request<{ run: import("./types").AgentRun }>(
    `/api/v1/agent-runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST", body: JSON.stringify({}) },
  );
}

export async function subscribeAgentRunEvents(
  runId: string,
  opts: {
    lastEventId: number;
    signal?: AbortSignal;
    onEnvelope: (envelope: import("./runSse").RunSseEnvelope) => void;
  },
): Promise<void> {
  const { subscribeRunEvents } = await import("./runSse");
  return subscribeRunEvents({
    url: `/api/v1/agent-runs/${encodeURIComponent(runId)}/events`,
    lastEventId: opts.lastEventId,
    signal: opts.signal,
    onEnvelope: opts.onEnvelope,
    isTerminal: (envelope) => {
      const type = String(
        envelope.data["type"] ?? envelope.data["event"] ?? "",
      );
      return type === "done" || type === "error" || type === "cancelled";
    },
  });
}

// --- Task Agent APIs ---

import type {
  TaskAgentCapability,
  TaskAgentCapabilityUpdate,
  TaskAgentCreateRequest,
  TaskAgentListResponse,
  TaskAgentProjectResolutionBody,
  TaskAgentTargetOptionsResponse,
  TaskAgentTask,
  TaskAgentTaskDetail,
} from "./types";

export function createTaskAgentTask(
  body: TaskAgentCreateRequest,
): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(`/api/v1/task-agent/tasks`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listTaskAgentTasks(params: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<TaskAgentListResponse> {
  return request<TaskAgentListResponse>(
    withQuery("/api/v1/task-agent/tasks", {
      status: params.status,
      limit: params.limit,
      offset: params.offset,
    }),
  );
}

export function getTaskAgentTask(taskId: string): Promise<TaskAgentTaskDetail> {
  return request<TaskAgentTaskDetail>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}`,
  );
}

export function approveTaskAgentTask(taskId: string): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}/approve`,
    { method: "POST" },
  );
}

export function rejectTaskAgentTask(
  taskId: string,
  reason: string,
): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ reason }),
    },
  );
}

export function cancelTaskAgentTask(taskId: string): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}/cancel`,
    { method: "POST" },
  );
}

export function replanTaskAgentTask(taskId: string): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}/replan`,
    { method: "POST" },
  );
}

export function listTaskAgentTargetOptions(): Promise<TaskAgentTargetOptionsResponse> {
  return request<TaskAgentTargetOptionsResponse>(
    `/api/v1/task-agent/target-options`,
  );
}

export function setTaskAgentProjectResolution(
  taskId: string,
  body: TaskAgentProjectResolutionBody,
): Promise<TaskAgentTask> {
  return request<TaskAgentTask>(
    `/api/v1/task-agent/tasks/${encodeURIComponent(taskId)}/project-resolution`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function listTaskAgentCapabilities(): Promise<TaskAgentCapability[]> {
  return request<TaskAgentCapability[]>(`/api/v1/task-agent/capabilities`);
}

export function updateTaskAgentCapability(
  capabilityKey: string,
  update: TaskAgentCapabilityUpdate,
): Promise<TaskAgentCapability> {
  return request<TaskAgentCapability>(
    `/api/v1/task-agent/capabilities/${encodeURIComponent(capabilityKey)}`,
    {
      method: "PUT",
      body: JSON.stringify(update),
    },
  );
}

// --- Workflow --------------------------------------------------------------

export function listWorkflows(params: {
  limit?: number;
  offset?: number;
} = {}): Promise<WorkflowListResponse> {
  return request<WorkflowListResponse>(withQuery("/api/v1/workflows", params));
}

export function createWorkflow(payload: {
  name: string;
  description?: string;
  inputs_schema?: Record<string, unknown>;
}): Promise<WorkflowDetail> {
  return request<WorkflowDetail>("/api/v1/workflows", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getWorkflow(workflowId: string): Promise<WorkflowDetail> {
  return request<WorkflowDetail>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
  );
}

export function updateWorkflow(
  workflowId: string,
  payload: { name?: string; description?: string },
): Promise<WorkflowDetail> {
  return request<WorkflowDetail>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
}

export function deleteWorkflow(
  workflowId: string,
): Promise<{ success: boolean; workflow_id: string }> {
  return request<{ success: boolean; workflow_id: string }>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
    { method: "DELETE" },
  );
}

export function createWorkflowRevision(
  workflowId: string,
): Promise<WorkflowRevision> {
  return request<WorkflowRevision>(
    `/api/v1/workflows/${encodeURIComponent(workflowId)}/revisions`,
    { method: "POST" },
  );
}

export function listWorkflowCapabilities(): Promise<WorkflowCapabilityListResponse> {
  return request<WorkflowCapabilityListResponse>("/api/v1/workflows/capabilities");
}

export function getWorkflowRevision(
  revisionId: string,
): Promise<WorkflowRevision> {
  return request<WorkflowRevision>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}`,
  );
}

export function updateWorkflowRevision(
  revisionId: string,
  payload: {
    inputs_schema: Record<string, unknown>;
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
  },
): Promise<WorkflowRevision> {
  return request<WorkflowRevision>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export function validateWorkflowRevision(
  revisionId: string,
): Promise<WorkflowValidationResponse> {
  return request<WorkflowValidationResponse>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}/validate`,
    { method: "POST" },
  );
}

export function publishWorkflowRevision(
  revisionId: string,
): Promise<WorkflowRevision> {
  return request<WorkflowRevision>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}/publish`,
    { method: "POST" },
  );
}

export function deleteWorkflowRevision(
  revisionId: string,
): Promise<{ success: boolean; revision_id: string }> {
  return request<{ success: boolean; revision_id: string }>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}`,
    { method: "DELETE" },
  );
}

export function createWorkflowRun(
  revisionId: string,
  inputs: Record<string, unknown>,
): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/revisions/${encodeURIComponent(revisionId)}/runs`,
    { method: "POST", body: JSON.stringify({ inputs }) },
  );
}

export function rerunWorkflowRun(
  runId: string,
  inputs?: Record<string, unknown>,
): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}/rerun`,
    { method: "POST", body: JSON.stringify(inputs === undefined ? {} : { inputs }) },
  );
}

export function getWorkflowRun(runId: string): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}`,
  );
}

export function approveWorkflowRun(runId: string): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}/approve`,
    { method: "POST" },
  );
}

export function cancelWorkflowRun(runId: string): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}/cancel`,
    { method: "POST" },
  );
}

export function resumeWorkflowRun(runId: string): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}/resume`,
    { method: "POST" },
  );
}

export function resolveWorkflowAttention(
  runId: string,
  payload: { decision: "adopt" | "fail" | "reexecute" | "interrupt" },
): Promise<WorkflowRun> {
  return request<WorkflowRun>(
    `/api/v1/workflows/runs/${encodeURIComponent(runId)}/attention`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function listWorkflowTemplates(): Promise<WorkflowTemplateListResponse> {
  return request<WorkflowTemplateListResponse>("/api/v1/workflows/templates");
}

export function createWorkflowFromTemplate(payload: {
  template_key: string;
  name?: string;
}): Promise<WorkflowDetail> {
  return request<WorkflowDetail>("/api/v1/workflows/from-template", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
