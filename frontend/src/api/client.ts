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
} from "./types";

const TOKEN_KEY = "obsidian-ai-hub:review-token";

// TODO: migrate to httpOnly cookie once backend supports cookie-based auth
// to prevent token exfiltration via XSS.

export function getToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token: string): void {
  if (token) {
    sessionStorage.setItem(TOKEN_KEY, token);
  } else {
    sessionStorage.removeItem(TOKEN_KEY);
  }
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
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
    throw new ApiError(401, "Authentication failed. Please check your token.");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body?.detail || detail;
    } catch (_) {
      // ignore
    }
    throw new ApiError(res.status, detail);
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

export async function health(): Promise<{ status: string; auth_required: boolean }> {
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

export function reviewResearchTheme(
  themeId: string,
  action: "approve" | "reject",
  reason?: string,
): Promise<{ theme: ResearchTheme }> {
  return request<{ theme: ResearchTheme }>(
    `/api/v1/research-themes/${encodeURIComponent(themeId)}/review`,
    {
      method: "POST",
      body: JSON.stringify({ action, reason }),
    },
  );
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
