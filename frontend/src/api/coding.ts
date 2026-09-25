import { apiGet, apiPost, apiPut, apiDelete, getToken, clearToken, AUTH_EXPIRED_EVENT, ApiError, withQuery } from "./client";
import type { Project, AskUserAnswerRound } from "./types";
import type { QuestionItem } from "../components/InConversationQuestionCard";

export interface CodingTool {
  tool_id: string;
  name: string;
  description: string;
}

export interface CodingDefaults {
  default_tool_ids: string[];
  available_tools: CodingTool[];
}

export interface CodingConfig {
  default_backend: "opencode";
  opencode_model?: string | null;
  available_models?: string[];
  orchestrator_provider?: string | null;
  orchestrator_model?: string | null;
  available_orchestrator_providers?: string[];
}

export interface GitStatus {
  branch: string;
  ahead: number;
  behind: number;
  insertions: number;
  deletions: number;
}

export interface CodingProjectItem {
  project: Project;
  is_valid_git_repo: boolean;
  repo_path: string | null;
  error_message: string | null;
}

export interface CodingSession {
  session_id: string;
  project_id: number;
  backend: string;
  repo_path: string;
  external_session_id: string | null;
  title: string;
  tool_ids_json?: string | null;
  // "direct_cli" persists on legacy read-only rows; new sessions are always "acp".
  transport: "acp" | "direct_cli";
  acp_session_id?: string | null;
  acp_profile_id?: string | null;
  opencode_model?: string | null;
  /** Per-session orchestrator override; null inherits the config default. */
  orchestrator_provider?: string | null;
  orchestrator_model?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CodingDiagnosticsUsage {
  input?: number | null;
  output?: number | null;
  total?: number | null;
  cached?: number | null;
  /** Cumulative tokens used (ACP usage_update `used`). */
  used?: number | null;
  /** Context window size (ACP usage_update `size`). */
  size?: number | null;
  /** Billed cost (ACP usage_update `cost`). */
  cost?: { amount?: number | null; currency?: string | null } | null;
}

/** Run-wide accumulation across every worker attempt in one run. */
export interface CodingDiagnosticsUsageCumulative {
  input?: number | null;
  output?: number | null;
  total?: number | null;
  cached?: number | null;
  /** Max context-window usage observed (never summed; it is a snapshot). */
  used_max?: number | null;
  /** Context window size observed. */
  size_max?: number | null;
  /** Summed cost across attempts. */
  cost?: { amount?: number | null; currency?: string | null } | null;
}

export interface CodingDiagnostics {
  // 新ACP診断（任意）。旧direct_cli runは旧キーのみ持つ。
  transport?: string | null;
  acp_session_id?: string | null;
  acp_version?: number | string | null;
  acp_profile_id?: string | null;
  acp_model?: string | null;
  acp_agent?: { name?: string | null; version?: string | null } | null;
  stop_reason?: string | null;
  session_recreated?: boolean | null;
  stderr_snippet?: string | null;
  worker_tool_call_count?: number | null;
  worker_tool_failure_count?: number | null;
  usage?: CodingDiagnosticsUsage | null;
  /** Aggregate over all worker attempts in the run (present when usage existed). */
  usage_cumulative?: CodingDiagnosticsUsageCumulative | null;
  /** Number of worker attempts that contributed to the run. */
  worker_attempt_count?: number | null;
  exit_code?: number | null;
  error?: string | null;
  // 旧direct_cli診断（後方互換のため読取のみ）。
  cwd?: string | null;
  requested_session_id?: string | null;
  returned_session_id?: string | null;
  tool_call_count?: number | null;
  tool_failure_count?: number | null;
  structured_error?: string | null;
  auto_rejected_permission?: boolean | null;
  model?: string | null;
  variant?: string | null;
}

export interface CodingMessage {
  message_id: string;
  session_id: string;
  sequence: number;
  role: "user" | "orchestrator" | "cli_request" | "worker";
  content: string;
  created_at: string;
  run_id?: string | null;
}

export interface CodingOrchestratorToolCall {
  call_id: string;
  run_id: string;
  phase: "initial" | "review";
  phase_turn: number;
  iteration: number;
  call_index: number;
  call_key: string;
  orchestrator_message_id?: string | null;
  tool_name: string;
  args: Record<string, unknown>;
  args_json?: string;
  result?: string | null;
  status: "running" | "succeeded" | "failed" | "interrupted";
  error?: string | null;
  provider_call_id?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface CodingLiveToolCall {
  id: string;
  call_id?: string;
  call_key?: string;
  tool_name: string;
  args: Record<string, unknown>;
  result: string;
  status: "preparing" | "running" | "succeeded" | "failed";
  error?: string | null;
  phase?: "initial" | "review";
  phase_turn?: number;
  iteration?: number;
  call_index?: number;
}

export type CodingRunStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "waiting_user"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface SlashInvocation {
  kind: "skill";
  name: string;
}

export interface SlashCandidate {
  kind: "skill";
  name: string;
  description: string;
}

export interface SlashCandidatesResponse {
  candidates: SlashCandidate[];
  has_skills_tool: boolean;
}

export interface CodingRun {
  run_id: string;
  session_id: string;
  user_message_id: string;
  orchestrator_message_id: string | null;
  worker_message_id: string | null;
  status: CodingRunStatus;
  hitl_run_id: string | null;
  dirty_tree_at_start: string | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
  diagnostics_json?: string | null;
  diagnostics?: CodingDiagnostics | null;
  slash_invocation?: SlashInvocation | null;
}

export interface CodingSessionDetail {
  session: CodingSession;
  effective_model?: string | null;
  available_models?: string[];
  effective_orchestrator_provider?: string | null;
  effective_orchestrator_model?: string | null;
  available_orchestrator_providers?: string[];
  default_orchestrator_provider?: string | null;
  default_orchestrator_model?: string | null;
  effective_tool_ids: string[];
  has_custom_tools: boolean;
  available_tools: CodingTool[];
  messages: CodingMessage[];
  orchestrator_tool_calls?: CodingOrchestratorToolCall[];
  active_run: CodingRun | null;
  latest_run: CodingRun | null;
  runs?: CodingRun[];
  ask_user_answer_history?: AskUserAnswerRound[];
}

export type CodingSseEvent =
  | { event: "start"; run_id: string; is_dirty: boolean; dirty_summary: string | null }
  | { event: "orchestrator_start"; phase: "initial" | "review"; phase_turn?: number }
  | {
      event: "orchestrator_tool_call_detected";
      call_key: string;
      tool_name: string;
      phase: "initial" | "review";
      phase_turn: number;
      iteration: number;
      call_index: number;
    }
  | {
      event: "orchestrator_tool_call_start";
      call_id: string;
      call_key: string;
      tool_name: string;
      args: Record<string, unknown>;
      phase: "initial" | "review";
      phase_turn: number;
      iteration: number;
      call_index: number;
    }
  | {
      event: "orchestrator_tool_call_end";
      call_id: string;
      call_key: string;
      tool_name: string;
      status: "succeeded" | "failed";
      result: string;
      error?: string | null;
      phase: "initial" | "review";
      phase_turn: number;
      iteration: number;
      call_index: number;
    }
  | { event: "orchestrator_message"; phase: "initial" | "review"; message: CodingMessage }
  | { event: "cli_request"; message: CodingMessage }
  | { event: "worker_start"; attempt: number; backend: string; prompt: string }
  | {
      event: "text_append";
      delta: string;
      phase?: "initial" | "review";
      phase_turn?: number;
      attempt?: number;
    }
  | {
      event: "acp_thought_append";
      delta: string;
      phase?: "initial" | "review";
      phase_turn?: number;
      attempt?: number;
    }
  | {
      event: "acp_tool_call";
      tool_call_id: string;
      tool_name?: string;
      kind?: string | null;
      status?: string | null;
      args?: Record<string, unknown>;
      locations?: { path: string }[];
      phase?: "initial" | "review";
      phase_turn?: number;
      attempt?: number;
    }
  | {
      event: "acp_tool_call_update";
      tool_call_id: string;
      tool_name?: string;
      kind?: string | null;
      status?: string | null;
      args?: Record<string, unknown>;
      locations?: { path: string }[];
      result?: string;
      error?: string | null;
      phase?: "initial" | "review";
      phase_turn?: number;
      attempt?: number;
    }
  | { event: "acp_plan"; entries: unknown[] }
  | {
      event: "worker_done";
      attempt: number;
      message: CodingMessage;
      exit_code: number;
      error: string | null;
      session_recreated?: boolean;
      git_status?: GitStatus;
      diagnostics?: CodingDiagnostics | null;
    }
  | { event: "done"; run_id: string; status: string; git_status?: GitStatus; session_title?: string }
  | { event: "user_question"; hitl_run_id: string; question_set_id: string; questions: QuestionItem[] }
  | { event: "cancelled"; message: string }
  | { event: "error"; message: string };

export function getGitStatus(repoPath: string): Promise<GitStatus> {
  return apiGet<GitStatus>(withQuery("/api/v1/coding/git-status", { repo_path: repoPath }));
}

export function listCodingProjects(): Promise<CodingProjectItem[]> {
  return apiGet<CodingProjectItem[]>("/api/v1/coding/projects");
}

export function listCodingSessions(projectId: number): Promise<CodingSession[]> {
  return apiGet<CodingSession[]>(withQuery("/api/v1/coding/sessions", { project_id: projectId }));
}

export function getCodingDefaults(): Promise<CodingDefaults> {
  return apiGet<CodingDefaults>("/api/v1/coding/defaults");
}

export function getCodingConfig(): Promise<CodingConfig> {
  return apiGet<CodingConfig>("/api/v1/coding/config");
}

export function updateCodingDefaults(toolIds: string[]): Promise<CodingDefaults> {
  return apiPut<CodingDefaults>("/api/v1/coding/defaults", { tool_ids: toolIds });
}

export function updateCodingSessionTools(
  sessionId: string,
  toolIds: string[] | null,
): Promise<CodingSessionDetail> {
  return apiPut<CodingSessionDetail>(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/tools`, {
    tool_ids: toolIds,
  });
}

export function updateCodingSessionTitle(
  sessionId: string,
  title: string,
): Promise<CodingSessionDetail> {
  return apiPut<CodingSessionDetail>(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}`, {
    title,
  });
}

export function createCodingSession(
  projectId: number,
  title?: string,
  toolIds?: string[],
): Promise<CodingSession> {
  // The server applies the config-derived default model; per-session changes
  // are made from the conversation status bar via updateCodingSessionModel.
  return apiPost<CodingSession>("/api/v1/coding/sessions", {
    project_id: projectId,
    backend: "opencode",
    title,
    tool_ids: toolIds,
    transport: "acp",
  });
}

export function updateCodingSessionModel(
  sessionId: string,
  opencodeModel: string,
): Promise<CodingSessionDetail> {
  return apiPut<CodingSessionDetail>(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/model`, {
    opencode_model: opencodeModel,
  });
}

export function updateCodingSessionOrchestrator(
  sessionId: string,
  orchestratorProvider: string | null,
  orchestratorModel: string | null,
): Promise<CodingSessionDetail> {
  return apiPut<CodingSessionDetail>(
    `/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/orchestrator`,
    {
      orchestrator_provider: orchestratorProvider,
      orchestrator_model: orchestratorModel,
    },
  );
}

export function getCodingSessionDetail(sessionId: string): Promise<CodingSessionDetail> {
  return apiGet<CodingSessionDetail>(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}`);
}

export function deleteCodingSession(sessionId: string): Promise<{ status: string; session_id: string }> {
  return apiDelete<{ status: string; session_id: string }>(
    `/api/v1/coding/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function cancelCodingRun(runId: string): Promise<{ status: string; run_id: string; run?: CodingRun }> {
  return apiPost<{ status: string; run_id: string; run?: CodingRun }>(
    `/api/v1/coding/runs/${encodeURIComponent(runId)}/cancel`,
    {},
  );
}

export function getSlashCandidates(sessionId: string): Promise<SlashCandidatesResponse> {
  return apiGet<SlashCandidatesResponse>(
    `/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/slash-candidates`,
  );
}

export function startCodingRun(
  sessionId: string,
  content: string,
  idempotencyKey?: string,
  slashInvocation?: SlashInvocation | null,
): Promise<{ run: CodingRun }> {
  const headers = new Headers();
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);
  return fetch(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/runs`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      content,
      slash_invocation: slashInvocation ?? null,
    }),
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
    return (await res.json()) as { run: CodingRun };
  });
}

export async function subscribeCodingRunEvents(
  runId: string,
  opts: {
    lastEventId: number;
    signal?: AbortSignal;
    onEnvelope: (envelope: import("./runSse").RunSseEnvelope) => void;
  },
): Promise<void> {
  const { subscribeRunEvents } = await import("./runSse");
  return subscribeRunEvents({
    url: `/api/v1/coding/runs/${encodeURIComponent(runId)}/events`,
    lastEventId: opts.lastEventId,
    signal: opts.signal,
    onEnvelope: opts.onEnvelope,
    // done/error/cancelled close the stream. waiting_user (user_question)
    // pauses via server disconnect; the caller resubscribes the same run ID
    // from the existing event cursor after the answer to replay in order.
    isTerminal: (envelope) => {
      const type = String(envelope.data["event"] ?? envelope.data["type"] ?? "");
      return type === "done" || type === "error" || type === "cancelled";
    },
  });
}
