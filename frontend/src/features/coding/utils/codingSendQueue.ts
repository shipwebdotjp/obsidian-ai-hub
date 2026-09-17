import type { SlashInvocation } from "../../../api/coding";

export type QueuedCodingMessageStatus = "pending" | "error";

export interface QueuedCodingMessage {
  queue_id: string;
  content: string;
  slash_invocation: SlashInvocation | null;
  idempotency_key: string;
  created_at: string;
  status: QueuedCodingMessageStatus;
  error_message: string | null;
}

export function buildCodingSendQueueKey(sessionId: string): string {
  return `coding-send-queue:${sessionId}:v1`;
}

export const CODING_SEND_QUEUE_SIZE_LIMIT = 1_000_000;

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

function isValidSlashInvocation(value: unknown): value is SlashInvocation {
  if (!value || typeof value !== "object") return false;
  const slash = value as SlashInvocation;
  return slash.kind === "skill" && typeof slash.name === "string";
}

function normalizeItem(value: unknown): QueuedCodingMessage | null {
  if (!value || typeof value !== "object") return null;
  const item = value as QueuedCodingMessage;
  if (
    typeof item.queue_id !== "string" ||
    typeof item.content !== "string" ||
    typeof item.idempotency_key !== "string"
  ) {
    return null;
  }
  if (item.slash_invocation != null && !isValidSlashInvocation(item.slash_invocation)) {
    return null;
  }
  return {
    queue_id: item.queue_id,
    content: item.content,
    slash_invocation: item.slash_invocation ?? null,
    idempotency_key: item.idempotency_key,
    created_at: typeof item.created_at === "string" ? item.created_at : "",
    status: item.status === "error" ? "error" : "pending",
    error_message: typeof item.error_message === "string" ? item.error_message : null,
  };
}

/** 指定セッションの送信待ちキューを読む。破損時は空配列。 */
export function readCodingSendQueue(sessionId: string): QueuedCodingMessage[] {
  try {
    const storage = getSessionStorage();
    if (!storage) return [];
    const raw = storage.getItem(buildCodingSendQueueKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { items?: unknown };
    const items = Array.isArray(parsed?.items) ? parsed.items : [];
    return items
      .map(normalizeItem)
      .filter((item): item is QueuedCodingMessage => item !== null);
  } catch {
    return [];
  }
}

export type CodingSendQueueWriteResult = "ok" | "too-large" | "unavailable";

/** 指定セッションの送信待ちキューを保存する。超過・不可時は例外を投げない。 */
export function writeCodingSendQueue(
  sessionId: string,
  items: QueuedCodingMessage[],
): CodingSendQueueWriteResult {
  try {
    const storage = getSessionStorage();
    if (!storage) return "unavailable";
    const key = buildCodingSendQueueKey(sessionId);
    if (items.length === 0) {
      storage.removeItem(key);
      return "ok";
    }
    const serialized = JSON.stringify({ version: 1, items });
    if (serialized.length > CODING_SEND_QUEUE_SIZE_LIMIT) {
      return "too-large";
    }
    storage.setItem(key, serialized);
    return "ok";
  } catch (e) {
    console.error("Failed to save coding send queue:", e);
    return "unavailable";
  }
}

/** 指定セッションの送信待ちキューを削除する（例外を投げない）。 */
export function removeCodingSendQueue(sessionId: string): void {
  try {
    getSessionStorage()?.removeItem(buildCodingSendQueueKey(sessionId));
  } catch {
    // ignore
  }
}

export interface CreateQueuedCodingMessageInput {
  content: string;
  slash_invocation?: SlashInvocation | null;
}

export function createQueuedCodingMessage(
  input: CreateQueuedCodingMessageInput,
): QueuedCodingMessage {
  return {
    queue_id: newId("cqmsg"),
    content: input.content,
    slash_invocation: input.slash_invocation ?? null,
    idempotency_key: newId("idem"),
    created_at: new Date().toISOString(),
    status: "pending",
    error_message: null,
  };
}

export function enqueueCodingMessage(
  items: QueuedCodingMessage[],
  item: QueuedCodingMessage,
): QueuedCodingMessage[] {
  return [...items, item];
}

export function removeQueuedCodingMessage(
  items: QueuedCodingMessage[],
  queueId: string,
): QueuedCodingMessage[] {
  return items.filter((item) => item.queue_id !== queueId);
}

export function markQueuedCodingMessageError(
  items: QueuedCodingMessage[],
  queueId: string,
  message: string,
): QueuedCodingMessage[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? { ...item, status: "error", error_message: message }
      : item,
  );
}

export function clearQueuedCodingMessageError(
  items: QueuedCodingMessage[],
  queueId: string,
): QueuedCodingMessage[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? { ...item, status: "pending", error_message: null }
      : item,
  );
}
