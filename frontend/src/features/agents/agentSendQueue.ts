import type { AgentMessageAttachment, SlashInvocation } from "../../api/types";

export type QueuedAgentMessageStatus = "pending" | "error";

export interface QueuedAgentMessage {
  queue_id: string;
  content: string;
  attachments: AgentMessageAttachment[];
  slash_invocation: SlashInvocation | null;
  idempotency_key: string;
  created_at: string;
  status: QueuedAgentMessageStatus;
  error_message: string | null;
}

export function buildAgentSendQueueKey(sessionId: string): string {
  return `agent-send-queue:${sessionId}:v1`;
}

export const AGENT_SEND_QUEUE_SIZE_LIMIT = 4_000_000;

function getSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function newId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isValidAttachment(value: unknown): value is AgentMessageAttachment {
  if (!value || typeof value !== "object") return false;
  const att = value as AgentMessageAttachment;
  return (
    typeof att.name === "string" &&
    typeof att.mime_type === "string" &&
    typeof att.data === "string"
  );
}

function isValidSlashInvocation(value: unknown): value is SlashInvocation {
  if (!value || typeof value !== "object") return false;
  const slash = value as SlashInvocation;
  return slash.kind === "skill" && typeof slash.name === "string";
}

function normalizeItem(value: unknown): QueuedAgentMessage | null {
  if (!value || typeof value !== "object") return null;
  const item = value as QueuedAgentMessage;
  if (
    typeof item.queue_id !== "string" ||
    typeof item.content !== "string" ||
    typeof item.idempotency_key !== "string" ||
    !Array.isArray(item.attachments) ||
    !item.attachments.every(isValidAttachment)
  ) {
    return null;
  }
  if (item.slash_invocation != null && !isValidSlashInvocation(item.slash_invocation)) {
    return null;
  }
  return {
    queue_id: item.queue_id,
    content: item.content,
    attachments: item.attachments.map((att) => ({ ...att })),
    slash_invocation: item.slash_invocation ?? null,
    idempotency_key: item.idempotency_key,
    created_at: typeof item.created_at === "string" ? item.created_at : "",
    status: item.status === "error" ? "error" : "pending",
    error_message: typeof item.error_message === "string" ? item.error_message : null,
  };
}

/** 指定セッションの送信待ちキューを読む。破損時は空配列。 */
export function readAgentSendQueue(sessionId: string): QueuedAgentMessage[] {
  try {
    const storage = getSessionStorage();
    if (!storage) return [];
    const raw = storage.getItem(buildAgentSendQueueKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { items?: unknown };
    const items = Array.isArray(parsed?.items) ? parsed.items : [];
    return items
      .map(normalizeItem)
      .filter((item): item is QueuedAgentMessage => item !== null);
  } catch {
    return [];
  }
}

export type AgentSendQueueWriteResult = "ok" | "too-large" | "unavailable";

/** 指定セッションの送信待ちキューを保存する。超過・不可時は例外を投げない。 */
export function writeAgentSendQueue(
  sessionId: string,
  items: QueuedAgentMessage[],
): AgentSendQueueWriteResult {
  try {
    const storage = getSessionStorage();
    if (!storage) return "unavailable";
    const key = buildAgentSendQueueKey(sessionId);
    if (items.length === 0) {
      storage.removeItem(key);
      return "ok";
    }
    const serialized = JSON.stringify({ version: 1, items });
    if (serialized.length > AGENT_SEND_QUEUE_SIZE_LIMIT) {
      return "too-large";
    }
    storage.setItem(key, serialized);
    return "ok";
  } catch (e) {
    console.error("Failed to save agent send queue:", e);
    return "unavailable";
  }
}

/** 指定セッションの送信待ちキューを削除する（例外を投げない）。 */
export function removeAgentSendQueue(sessionId: string): void {
  try {
    getSessionStorage()?.removeItem(buildAgentSendQueueKey(sessionId));
  } catch {
    // ignore
  }
}

export interface CreateQueuedMessageInput {
  content: string;
  attachments?: AgentMessageAttachment[];
  slash_invocation?: SlashInvocation | null;
}

export function createQueuedMessage(input: CreateQueuedMessageInput): QueuedAgentMessage {
  return {
    queue_id: newId("qmsg"),
    content: input.content,
    attachments: input.attachments ? input.attachments.map((att) => ({ ...att })) : [],
    slash_invocation: input.slash_invocation ?? null,
    idempotency_key: newId("idem"),
    created_at: new Date().toISOString(),
    status: "pending",
    error_message: null,
  };
}

export function enqueueAgentMessage(
  items: QueuedAgentMessage[],
  item: QueuedAgentMessage,
): QueuedAgentMessage[] {
  return [...items, item];
}

export function removeQueuedAgentMessage(
  items: QueuedAgentMessage[],
  queueId: string,
): QueuedAgentMessage[] {
  return items.filter((item) => item.queue_id !== queueId);
}

export function markQueuedAgentMessageError(
  items: QueuedAgentMessage[],
  queueId: string,
  message: string,
): QueuedAgentMessage[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? { ...item, status: "error", error_message: message }
      : item,
  );
}

export function clearQueuedAgentMessageError(
  items: QueuedAgentMessage[],
  queueId: string,
): QueuedAgentMessage[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? { ...item, status: "pending", error_message: null }
      : item,
  );
}
