import type { SlashInvocation } from "../../../api/types";
import {
  clearQueuedItemError,
  enqueueItem,
  markQueuedItemError,
  newId,
  normalizeBaseItem,
  readSendQueue,
  removeQueuedItem,
  removeSendQueue,
  writeSendQueue,
  type QueuedMessageBase,
  type QueuedMessageStatus,
  type SendQueueWriteResult,
} from "../../chat/sendQueue/core";

export type QueuedCodingMessageStatus = QueuedMessageStatus;

export type QueuedCodingMessage = QueuedMessageBase;

export function buildCodingSendQueueKey(sessionId: string): string {
  return `coding-send-queue:${sessionId}:v1`;
}

export const CODING_SEND_QUEUE_SIZE_LIMIT = 1_000_000;

function normalizeItem(value: unknown): QueuedCodingMessage | null {
  return normalizeBaseItem(value);
}

/** 指定セッションの送信待ちキューを読む。破損時は空配列。 */
export function readCodingSendQueue(sessionId: string): QueuedCodingMessage[] {
  return readSendQueue(buildCodingSendQueueKey(sessionId), normalizeItem);
}

export type CodingSendQueueWriteResult = SendQueueWriteResult;

/** 指定セッションの送信待ちキューを保存する。超過・不可時は例外を投げない。 */
export function writeCodingSendQueue(
  sessionId: string,
  items: QueuedCodingMessage[],
): CodingSendQueueWriteResult {
  return writeSendQueue(
    buildCodingSendQueueKey(sessionId),
    items,
    CODING_SEND_QUEUE_SIZE_LIMIT,
    "coding send queue",
  );
}

/** 指定セッションの送信待ちキューを削除する（例外を投げない）。 */
export function removeCodingSendQueue(sessionId: string): void {
  removeSendQueue(buildCodingSendQueueKey(sessionId));
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
  return enqueueItem(items, item);
}

export function removeQueuedCodingMessage(
  items: QueuedCodingMessage[],
  queueId: string,
): QueuedCodingMessage[] {
  return removeQueuedItem(items, queueId);
}

export function markQueuedCodingMessageError(
  items: QueuedCodingMessage[],
  queueId: string,
  message: string,
): QueuedCodingMessage[] {
  return markQueuedItemError(items, queueId, message);
}

export function clearQueuedCodingMessageError(
  items: QueuedCodingMessage[],
  queueId: string,
): QueuedCodingMessage[] {
  return clearQueuedItemError(items, queueId);
}
