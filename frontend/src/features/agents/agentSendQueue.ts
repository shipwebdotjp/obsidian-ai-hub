import type { AgentContextRef, AgentMessageAttachment, SlashInvocation } from "../../api/types";
import { isValidContextRef } from "./agentViewUtils";
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
} from "../chat/sendQueue/core";

export type QueuedAgentMessageStatus = QueuedMessageStatus;

export interface QueuedAgentMessage extends QueuedMessageBase {
  attachments: AgentMessageAttachment[];
  context_refs: AgentContextRef[];
}

export function buildAgentSendQueueKey(sessionId: string): string {
  return `agent-send-queue:${sessionId}:v1`;
}

export const AGENT_SEND_QUEUE_SIZE_LIMIT = 4_000_000;

function isValidAttachment(value: unknown): value is AgentMessageAttachment {
  if (!value || typeof value !== "object") return false;
  const att = value as AgentMessageAttachment;
  return (
    typeof att.name === "string" &&
    typeof att.mime_type === "string" &&
    typeof att.data === "string"
  );
}

function normalizeContextRefs(value: unknown): AgentContextRef[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isValidContextRef)
    .map((ref) => ({ kind: ref.kind, path: ref.path }));
}

function normalizeItem(value: unknown): QueuedAgentMessage | null {
  const base = normalizeBaseItem(value);
  if (!base) return null;
  const item = value as QueuedAgentMessage;
  if (!Array.isArray(item.attachments) || !item.attachments.every(isValidAttachment)) {
    return null;
  }
  return {
    ...base,
    attachments: item.attachments.map((att) => ({ ...att })),
    context_refs: normalizeContextRefs(item.context_refs),
  };
}

/** 指定セッションの送信待ちキューを読む。破損時は空配列。 */
export function readAgentSendQueue(sessionId: string): QueuedAgentMessage[] {
  return readSendQueue(buildAgentSendQueueKey(sessionId), normalizeItem);
}

export type AgentSendQueueWriteResult = SendQueueWriteResult;

/** 指定セッションの送信待ちキューを保存する。超過・不可時は例外を投げない。 */
export function writeAgentSendQueue(
  sessionId: string,
  items: QueuedAgentMessage[],
): AgentSendQueueWriteResult {
  return writeSendQueue(
    buildAgentSendQueueKey(sessionId),
    items,
    AGENT_SEND_QUEUE_SIZE_LIMIT,
    "agent send queue",
  );
}

/** 指定セッションの送信待ちキューを削除する（例外を投げない）。 */
export function removeAgentSendQueue(sessionId: string): void {
  removeSendQueue(buildAgentSendQueueKey(sessionId));
}

export interface CreateQueuedMessageInput {
  content: string;
  attachments?: AgentMessageAttachment[];
  slash_invocation?: SlashInvocation | null;
  context_refs?: AgentContextRef[];
}

export function createQueuedMessage(input: CreateQueuedMessageInput): QueuedAgentMessage {
  return {
    queue_id: newId("qmsg"),
    content: input.content,
    attachments: input.attachments ? input.attachments.map((att) => ({ ...att })) : [],
    slash_invocation: input.slash_invocation ?? null,
    context_refs: input.context_refs ? normalizeContextRefs(input.context_refs) : [],
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
  return enqueueItem(items, item);
}

export function removeQueuedAgentMessage(
  items: QueuedAgentMessage[],
  queueId: string,
): QueuedAgentMessage[] {
  return removeQueuedItem(items, queueId);
}

export function markQueuedAgentMessageError(
  items: QueuedAgentMessage[],
  queueId: string,
  message: string,
): QueuedAgentMessage[] {
  return markQueuedItemError(items, queueId, message);
}

export function clearQueuedAgentMessageError(
  items: QueuedAgentMessage[],
  queueId: string,
): QueuedAgentMessage[] {
  return clearQueuedItemError(items, queueId);
}
