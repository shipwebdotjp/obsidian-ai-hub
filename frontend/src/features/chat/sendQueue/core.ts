import type { SlashInvocation } from "../../../api/types";

export type QueuedMessageStatus = "pending" | "error";

export type SendQueueWriteResult = "ok" | "too-large" | "unavailable";

export interface QueuedMessageBase {
  queue_id: string;
  content: string;
  slash_invocation: SlashInvocation | null;
  idempotency_key: string;
  created_at: string;
  status: QueuedMessageStatus;
  error_message: string | null;
}

export function getSessionStorage(): Storage | null {
  try {
    if (typeof window === "undefined" || !window.sessionStorage) return null;
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function newId(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function isValidSlashInvocation(value: unknown): value is SlashInvocation {
  if (!value || typeof value !== "object") return false;
  const slash = value as SlashInvocation;
  return slash.kind === "skill" && typeof slash.name === "string";
}

/**
 * 共通フィールドを検証して正規化する。追加フィールド（例: 添付）の検証は
 * 呼び出し側の `parseItem` が担う。
 */
export function normalizeBaseItem(value: unknown): QueuedMessageBase | null {
  if (!value || typeof value !== "object") return null;
  const item = value as QueuedMessageBase;
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
export function readSendQueue<T>(
  key: string,
  parseItem: (value: unknown) => T | null,
): T[] {
  try {
    const storage = getSessionStorage();
    if (!storage) return [];
    const raw = storage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { items?: unknown };
    const items = Array.isArray(parsed?.items) ? parsed.items : [];
    return items
      .map(parseItem)
      .filter((item): item is T => item !== null);
  } catch {
    return [];
  }
}

/** 指定セッションの送信待ちキューを保存する。超過・不可時は例外を投げない。 */
export function writeSendQueue<T>(
  key: string,
  items: T[],
  sizeLimit: number,
  logLabel: string,
): SendQueueWriteResult {
  try {
    const storage = getSessionStorage();
    if (!storage) return "unavailable";
    if (items.length === 0) {
      storage.removeItem(key);
      return "ok";
    }
    const serialized = JSON.stringify({ version: 1, items });
    if (serialized.length > sizeLimit) {
      return "too-large";
    }
    storage.setItem(key, serialized);
    return "ok";
  } catch (e) {
    console.error(`Failed to save ${logLabel}:`, e);
    return "unavailable";
  }
}

/** 指定セッションの送信待ちキューを削除する（例外を投げない）。 */
export function removeSendQueue(key: string): void {
  try {
    getSessionStorage()?.removeItem(key);
  } catch {
    // ignore
  }
}

export function enqueueItem<T>(items: T[], item: T): T[] {
  return [...items, item];
}

export function removeQueuedItem<T extends { queue_id: string }>(
  items: T[],
  queueId: string,
): T[] {
  return items.filter((item) => item.queue_id !== queueId);
}

export function markQueuedItemError<
  T extends { queue_id: string; status: QueuedMessageStatus; error_message: string | null },
>(items: T[], queueId: string, message: string): T[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? ({ ...item, status: "error", error_message: message } as T)
      : item,
  );
}

export function clearQueuedItemError<
  T extends { queue_id: string; status: QueuedMessageStatus; error_message: string | null },
>(items: T[], queueId: string): T[] {
  return items.map((item) =>
    item.queue_id === queueId
      ? ({ ...item, status: "pending", error_message: null } as T)
      : item,
  );
}
