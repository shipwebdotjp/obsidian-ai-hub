import { apiGet, apiPost, apiDelete, getToken, clearToken, AUTH_EXPIRED_EVENT, ApiError } from "./client";
import type { Project } from "./types";

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
  created_at: string;
  updated_at: string;
}

export interface CodingMessage {
  message_id: string;
  session_id: string;
  sequence: number;
  role: "user" | "orchestrator" | "worker";
  content: string;
  created_at: string;
}

export interface CodingRun {
  run_id: string;
  session_id: string;
  user_message_id: string;
  orchestrator_message_id: string | null;
  worker_message_id: string | null;
  status: "running" | "completed" | "failed" | "cancelled" | "interrupted";
  dirty_tree_at_start: string | null;
  error_message: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface CodingSessionDetail {
  session: CodingSession;
  messages: CodingMessage[];
  active_run: CodingRun | null;
  latest_run: CodingRun | null;
}

export type CodingSseEvent =
  | { event: "start"; run_id: string; is_dirty: boolean; dirty_summary: string | null }
  | { event: "orchestrator_chunk"; text: string }
  | { event: "worker_start"; backend: string; prompt: string }
  | { event: "worker_done"; output: string; exit_code: number; error: string | null }
  | { event: "done"; run_id: string; status: string }
  | { event: "cancelled"; message: string }
  | { event: "error"; message: string };

export function listCodingProjects(): Promise<CodingProjectItem[]> {
  return apiGet<CodingProjectItem[]>("/api/v1/coding/projects");
}

export function listCodingSessions(projectId: number): Promise<CodingSession[]> {
  return apiGet<CodingSession[]>(`/api/v1/coding/sessions?project_id=${projectId}`);
}

export function createCodingSession(
  projectId: number,
  backend: string,
  title?: string,
): Promise<CodingSession> {
  return apiPost<CodingSession>("/api/v1/coding/sessions", {
    project_id: projectId,
    backend,
    title,
  });
}

export function getCodingSessionDetail(sessionId: string): Promise<CodingSessionDetail> {
  return apiGet<CodingSessionDetail>(`/api/v1/coding/sessions/${encodeURIComponent(sessionId)}`);
}

export function deleteCodingSession(sessionId: string): Promise<{ status: string; session_id: string }> {
  return apiDelete<{ status: string; session_id: string }>(
    `/api/v1/coding/sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function cancelCodingRun(runId: string): Promise<{ status: string; run_id: string }> {
  return apiPost<{ status: string; run_id: string }>(
    `/api/v1/coding/runs/${encodeURIComponent(runId)}/cancel`,
    {},
  );
}

export async function streamCodingMessage(
  sessionId: string,
  content: string,
  onEvent: (event: CodingSseEvent) => void,
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
    `/api/v1/coding/sessions/${encodeURIComponent(sessionId)}/messages/stream`,
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

    let remainder = buffer;
    while (true) {
      const separator = /\r?\n\r?\n/.exec(remainder);
      if (!separator || separator.index === undefined) break;

      const eventBlock = remainder.slice(0, separator.index);
      remainder = remainder.slice(separator.index + separator[0].length);

      const dataLines: string[] = [];
      for (const line of eventBlock.split(/\r?\n/)) {
        if (line.startsWith("data:")) {
          let data = line.slice(5);
          if (data.startsWith(" ")) data = data.slice(1);
          dataLines.push(data);
        }
      }

      if (dataLines.length > 0) {
        try {
          const parsed = JSON.parse(dataLines.join("\n")) as CodingSseEvent;
          onEvent(parsed);
        } catch (e) {
          console.error("Failed to parse SSE event:", eventBlock, e);
        }
      }
    }
    buffer = remainder;
  }
}
