import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { getErrorMessage } from "../../utils/error";
import { useCopyMessage } from "../../hooks/useCopyMessage";
import {
  cancelAgentRun,
  startAgentRun,
  subscribeAgentRunEvents,
} from "../../api/client";
import type {
  Agent,
  AgentLiveToolCall,
  AgentMessage,
  AgentMessageAttachment,
  AgentRun,
  AgentRunStatus,
  AgentSession,
  SlashInvocation,
} from "../../api/types";
import {
  loadLastAppliedId,
  saveLastAppliedId,
  type RunSseEnvelope,
} from "../../api/runSse";
import type {
  ActiveWaitingRun,
  QuestionItem,
} from "../../components/InConversationQuestionCard";
import { useAgentImageDraft } from "./useAgentImageDraft";
import {
  clearQueuedAgentMessageError,
  createQueuedMessage,
  enqueueAgentMessage,
  markQueuedAgentMessageError,
  readAgentSendQueue,
  removeQueuedAgentMessage,
  writeAgentSendQueue,
  type AgentSendQueueWriteResult,
  type QueuedAgentMessage,
} from "./agentSendQueue";
import {
  MAX_AGENT_IMAGES,
  MAX_AGENT_IMAGE_BYTES,
  matchesLiveToolCall,
  type PendingAttachment,
} from "./agentViewUtils";

const NON_TERMINAL_RUN_STATUSES = new Set<AgentRunStatus>([
  "queued",
  "running",
  "cancelling",
  "waiting_user",
]);

interface AgentSendSnapshot {
  content: string;
  rawText: string;
  attachments: AgentMessageAttachment[];
  attachmentDrafts: PendingAttachment[];
  slashInvocation: SlashInvocation | null;
  idempotencyKey: string;
}

interface SendRunOptions {
  sessionId: string;
  snapshot: AgentSendSnapshot;
  mode: "composer" | "queue";
  onAccepted?: () => void;
  onPostError?: (error: unknown) => void;
}

function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isAbortError(err: unknown): boolean {
  return (
    (err instanceof DOMException && err.name === "AbortError") ||
    (typeof err === "object" &&
      err !== null &&
      "name" in err &&
      (err as { name: string }).name === "AbortError")
  );
}

interface UseAgentChatOptions {
  selectedSessionId: string | null;
  selectedAgentId: string | null;
  activeAgent: Agent | undefined;
  onChatError: (message: string | null) => void;
  loadSessions: (agentId: string) => Promise<void>;
  loadSessionDetail: (
    sessionId: string,
    options?: { preserveChatError?: boolean },
  ) => Promise<void>;
  messages: AgentMessage[];
  setMessages: React.Dispatch<React.SetStateAction<AgentMessage[]>>;
  runs: AgentRun[];
  loadedSessionId: string | null;
  activeWaitingRun: ActiveWaitingRun | null;
  setActiveWaitingRun: React.Dispatch<React.SetStateAction<ActiveWaitingRun | null>>;
  setSessions: React.Dispatch<React.SetStateAction<AgentSession[]>>;
  inputText: string;
  savePromptDraftFor: (sessionId: string, text: string) => void;
  setPromptInputLocal: (text: string) => void;
  removePromptDraftFor: (sessionId: string) => void;
  imageInputRef: MutableRefObject<HTMLInputElement | null>;
}

/** チャット送信・SSE購読・添付画像・ストリーミング表示状態を管理する。 */
export function useAgentChat({
  selectedSessionId,
  selectedAgentId,
  activeAgent,
  onChatError,
  loadSessions,
  loadSessionDetail,
  messages,
  setMessages,
  runs,
  loadedSessionId,
  activeWaitingRun,
  setActiveWaitingRun,
  setSessions,
  inputText,
  savePromptDraftFor,
  setPromptInputLocal,
  removePromptDraftFor,
  imageInputRef,
}: UseAgentChatOptions) {
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamingToolCalls, setStreamingToolCalls] = useState<AgentLiveToolCall[]>([]);
  const [streamingPhase, setStreamingPhase] = useState<"thinking" | "tool_preparing" | "tool_running" | null>(null);
  const [streamingIteration, setStreamingIteration] = useState<number | null>(null);
  const [hitlLinks, setHitlLinks] = useState<string[]>([]);
  const { copiedMessageId, handleCopyMessage } = useCopyMessage();
  const [selectedSkill, setSelectedSkill] = useState<SlashInvocation | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentReadsPending, setAttachmentReadsPending] = useState(0);
  const [isDragOver, setIsDragOver] = useState(false);
  const [queuedMessages, setQueuedMessages] = useState<QueuedAgentMessage[]>([]);

  // Send queue (ai_wiki/10-Decisions-Web.md: エージェント会話の送信キューは
  // クライアント側に置く). The ref is the flush source of truth; state mirrors
  // only the selected session for rendering.
  const queueRef = useRef<{ sessionId: string | null; items: QueuedAgentMessage[] }>({
    sessionId: null,
    items: [],
  });
  const flushInFlightRef = useRef(false);
  const queueBlockedRef = useRef(false);
  const queueRetryTimerRef = useRef<number | null>(null);
  const flushQueueRef = useRef<() => void>(() => {});
  const selectedSessionIdRef = useRef<string | null>(selectedSessionId);
  const loadedSessionIdRef = useRef<string | null>(loadedSessionId);
  const activeWaitingRunRef = useRef<ActiveWaitingRun | null>(activeWaitingRun);
  const runsRef = useRef<AgentRun[]>(runs);
  const isStreamingRef = useRef(false);
  const inputTextRef = useRef(inputText);
  const pendingAttachmentsRef = useRef<PendingAttachment[]>(pendingAttachments);
  const loadSessionDetailRef = useRef(loadSessionDetail);
  const onChatErrorRef = useRef(onChatError);
  const updateQueueRef = useRef<
    (
      sessionId: string,
      updater: (items: QueuedAgentMessage[]) => QueuedAgentMessage[],
    ) => AgentSendQueueWriteResult
  >(() => "ok");
  const sendRunRef = useRef<(options: SendRunOptions) => Promise<void>>(async () => {});

  selectedSessionIdRef.current = selectedSessionId;
  loadedSessionIdRef.current = loadedSessionId;
  activeWaitingRunRef.current = activeWaitingRun;
  runsRef.current = runs;
  isStreamingRef.current = isStreaming;
  inputTextRef.current = inputText;
  pendingAttachmentsRef.current = pendingAttachments;
  loadSessionDetailRef.current = loadSessionDetail;
  onChatErrorRef.current = onChatError;

  // Reconnectable run subscription state (docs/run-sse).
  // AbortController here aborts only the subscription; it never cancels the run.
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const lastAppliedEventIdRef = useRef(0);
  const streamGenerationRef = useRef(0);
  const streamingTextBufferRef = useRef("");
  const streamingTextFrameRef = useRef<number | null>(null);

  // 添付画像の下書きはセッションごとに localStorage へデバウンス保存・復元する。
  // テキスト下書きとはキー・保存先を分離し、同一Agentsセッションに対応付ける。
  const {
    saveImageDraftFor,
    removeImageDraftFor,
    setLocalAttachments,
  } = useAgentImageDraft(
    selectedSessionId,
    pendingAttachments,
    setPendingAttachments,
    inputText,
    () => onChatError("下書きが大きすぎて保存できません（画像を減らしてください）。"),
  );

  const updateQueue = useCallback(
    (
      sessionId: string,
      updater: (items: QueuedAgentMessage[]) => QueuedAgentMessage[],
    ): AgentSendQueueWriteResult => {
      const current =
        queueRef.current.sessionId === sessionId
          ? queueRef.current.items
          : readAgentSendQueue(sessionId);
      const next = updater(current);
      const result = writeAgentSendQueue(sessionId, next);
      if (result !== "ok") {
        // Do not commit unpersisted state: a reload would restore the old queue
        // and the UI would diverge from storage.
        onChatErrorRef.current(
          result === "too-large"
            ? "待機メッセージが大きすぎて保存できません（画像を減らしてください）。"
            : "待機メッセージの保存に失敗しました。",
        );
        return result;
      }
      queueRef.current = { sessionId, items: next };
      if (selectedSessionIdRef.current === sessionId) {
        setQueuedMessages(next);
      }
      return result;
    },
    [],
  );
  updateQueueRef.current = updateQueue;

  const clearQueueRetry = useCallback(() => {
    if (queueRetryTimerRef.current !== null) {
      window.clearTimeout(queueRetryTimerRef.current);
      queueRetryTimerRef.current = null;
    }
  }, []);

  // Restore the persisted queue for the selected session. Other sessions keep
  // their queues in storage and are only flushed once selected again.
  useEffect(() => {
    queueBlockedRef.current = false;
    clearQueueRetry();
    if (!selectedSessionId) {
      queueRef.current = { sessionId: null, items: [] };
      setQueuedMessages([]);
      return;
    }
    const items = readAgentSendQueue(selectedSessionId);
    queueRef.current = { sessionId: selectedSessionId, items };
    setQueuedMessages(items);
  }, [selectedSessionId, clearQueueRetry]);

  const invalidatePendingStreamingText = useCallback(() => {
    streamGenerationRef.current += 1;
    streamingTextBufferRef.current = "";
    if (streamingTextFrameRef.current !== null) {
      window.cancelAnimationFrame(streamingTextFrameRef.current);
      streamingTextFrameRef.current = null;
    }
  }, []);

  const enqueueStreamingText = useCallback((delta: string, generation: number) => {
    if (generation !== streamGenerationRef.current) return;
    streamingTextBufferRef.current += delta;
    if (streamingTextFrameRef.current !== null) return;

    streamingTextFrameRef.current = window.requestAnimationFrame(() => {
      streamingTextFrameRef.current = null;
      if (generation !== streamGenerationRef.current) return;

      const bufferedText = streamingTextBufferRef.current;
      streamingTextBufferRef.current = "";
      if (bufferedText) {
        setStreamingText((previous) => previous + bufferedText);
      }
    });
  }, []);

  const resetStreamingState = useCallback(() => {
    invalidatePendingStreamingText();
    setIsStreaming(false);
    setStreamingText("");
    setStreamingToolCalls([]);
    setStreamingPhase(null);
    setStreamingIteration(null);
  }, [invalidatePendingStreamingText]);

  /** セッション/エージェント切替時に購読だけを破棄し、表示を初期化する。 */
  const abortSubscriptionAndReset = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    resetStreamingState();
  }, [resetStreamingState]);

  // --- Reconnectable run subscription (docs/run-sse) ---
  // Server event log is the source of truth; sessionStorage caches only the
  // last applied event id. Abort here stops only the subscription, never the run.
  const handleRunEnvelope = useCallback(
    (
      envelope: RunSseEnvelope,
      ctx: {
        streamSessionId: string;
        streamGeneration: number;
        isCurrentStream: () => boolean;
        finalizeSendSuccess: () => void;
        restoreSendText: () => void;
        removeTempMessage?: () => void;
      },
    ) => {
      if (!ctx.isCurrentStream()) return;
      // At-least-once: ignore re-sent IDs.
      if (envelope.eventId <= lastAppliedEventIdRef.current) return;
      lastAppliedEventIdRef.current = envelope.eventId;
      const runId = activeRunIdRef.current;
      if (runId) saveLastAppliedId("agent", runId, envelope.eventId);

      const data = envelope.data as Record<string, unknown> & {
        type?: string;
        iteration?: number;
        call_key?: string;
        call_id?: string;
        tool_name?: string;
        args?: Record<string, unknown>;
        result?: string;
        status?: AgentLiveToolCall["status"];
        hitl_run_id?: string | null;
        error?: string | null;
        delta?: string;
        question_set_id?: string;
        questions?: QuestionItem[];
        hitl_run_ids?: string[];
        session_title?: string;
        error_message?: string;
      };
      const type = String(data.type ?? "");
      if (type === "thinking") {
        setStreamingPhase("thinking");
        if (typeof data.iteration === "number") setStreamingIteration(data.iteration);
      } else if (type === "tool_call_detected") {
        const callKey = String(data.call_key ?? "");
        const toolName = String(data.tool_name ?? "");
        if (!callKey || !toolName) return;
        setStreamingPhase("tool_preparing");
        if (typeof data.iteration === "number") setStreamingIteration(data.iteration);
        setStreamingToolCalls((previous) => {
          if (previous.some((toolCall) => matchesLiveToolCall(toolCall, callKey))) {
            return previous;
          }
          return [
            ...previous,
            {
              id: callKey,
              call_key: callKey,
              tool_name: toolName,
              args: {},
              result: "",
              status: "preparing",
              hitl_run_id: null,
              error: null,
              iteration: typeof data.iteration === "number" ? data.iteration : 0,
            },
          ];
        });
      } else if (type === "tool_call_start") {
        const callId = String(data.call_id ?? "");
        const toolName = String(data.tool_name ?? "");
        if (!callId || !toolName) return;
        if (typeof data.iteration === "number") setStreamingIteration(data.iteration);
        setStreamingPhase("tool_running");
        setStreamingToolCalls((previous) => {
          const callKey = typeof data.call_key === "string" ? data.call_key : undefined;
          const existingIndex = previous.findIndex((toolCall) =>
            matchesLiveToolCall(toolCall, callKey, callId),
          );
          const existing = existingIndex >= 0 ? previous[existingIndex] : undefined;
          const nextToolCall: AgentLiveToolCall = {
            id: existing?.id ?? callKey ?? callId,
            call_id: callId,
            call_key: callKey ?? existing?.call_key,
            tool_name: toolName,
            args: (data.args as Record<string, unknown>) ?? {},
            result: existing?.result ?? "",
            status: "running",
            hitl_run_id: existing?.hitl_run_id ?? null,
            error: null,
            iteration: typeof data.iteration === "number" ? data.iteration : (existing?.iteration ?? 0),
          };
          if (existingIndex >= 0) {
            return previous.map((toolCall, index) =>
              index === existingIndex ? nextToolCall : toolCall,
            );
          }
          return [...previous, nextToolCall];
        });
      } else if (type === "tool_call_end") {
        if (typeof data.iteration === "number") setStreamingIteration(data.iteration);
        setStreamingToolCalls((previous) => {
          const callKey = typeof data.call_key === "string" ? data.call_key : undefined;
          const callId = typeof data.call_id === "string" ? data.call_id : undefined;
          const existingIndex = previous.findIndex((toolCall) =>
            matchesLiveToolCall(toolCall, callKey, callId),
          );
          const status = (data.status as AgentLiveToolCall["status"]) ?? "succeeded";
          if (existingIndex < 0) {
            return [
              ...previous,
              {
                id: (callKey ?? callId ?? "") as string,
                call_id: callId,
                call_key: callKey,
                tool_name: String(data.tool_name ?? ""),
                args: {},
                result: String(data.result ?? ""),
                status,
                hitl_run_id: (data.hitl_run_id as string | null) ?? null,
                error: (data.error as string | null) ?? null,
                iteration: typeof data.iteration === "number" ? data.iteration : 0,
              },
            ];
          }
          return previous.map((toolCall, index) =>
            index === existingIndex
              ? {
                  ...toolCall,
                  call_id: callId ?? toolCall.call_id,
                  call_key: callKey ?? toolCall.call_key,
                  tool_name: String(data.tool_name ?? toolCall.tool_name),
                  result: String(data.result ?? ""),
                  status,
                  hitl_run_id: (data.hitl_run_id as string | null) ?? null,
                  error: (data.error as string | null) ?? null,
                  iteration: typeof data.iteration === "number" ? data.iteration : toolCall.iteration,
                }
              : toolCall,
          );
        });
        setStreamingPhase("thinking");
      } else if (type === "text_append") {
        enqueueStreamingText(String(data.delta ?? ""), ctx.streamGeneration);
        setStreamingPhase(null);
      } else if (type === "user_question") {
        ctx.finalizeSendSuccess();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        const hitlRunId = String(data.hitl_run_id ?? "");
        const questions = Array.isArray(data.questions)
          ? (data.questions as QuestionItem[])
          : [];
        if (hitlRunId) setActiveWaitingRun({ hitlRunId, questions, hitlStatus: "pending_user" });
        void loadSessionDetail(ctx.streamSessionId);
      } else if (type === "done") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.finalizeSendSuccess();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        void loadSessionDetail(ctx.streamSessionId);
        const sessionTitle = typeof data.session_title === "string" ? data.session_title : undefined;
        if (sessionTitle) {
          setSessions((prev) =>
            prev.map((s) =>
              s.session_id === ctx.streamSessionId ? { ...s, title: sessionTitle } : s,
            ),
          );
        }
        if (selectedAgentId) void loadSessions(selectedAgentId);
        const hitlIds = Array.isArray(data.hitl_run_ids) ? (data.hitl_run_ids as string[]) : [];
        if (hitlIds.length > 0) setHitlLinks(hitlIds);
      } else if (type === "error") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.restoreSendText();
        ctx.removeTempMessage?.();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        onChatError(String(data.error ?? data.error_message ?? "エラーが発生しました。"));
        void loadSessionDetail(ctx.streamSessionId, { preserveChatError: true });
      } else if (type === "cancelled") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.restoreSendText();
        ctx.removeTempMessage?.();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        onChatError("キャンセルされました");
        void loadSessionDetail(ctx.streamSessionId, { preserveChatError: true });
      }
    },
    [
      clearQueueRetry,
      enqueueStreamingText,
      loadSessions,
      resetStreamingState,
      selectedAgentId,
    ],
  );

  const subscribeToAgentRun = useCallback(
    async (
      runId: string,
      streamSessionId: string,
      fromEventId: number,
      ctx: {
        streamGeneration: number;
        isCurrentStream: () => boolean;
        finalizeSendSuccess: () => void;
        restoreSendText: () => void;
        removeTempMessage?: () => void;
      },
    ) => {
      lastAppliedEventIdRef.current = fromEventId;
      activeRunIdRef.current = runId;
      const controller = abortControllerRef.current;
      try {
        await subscribeAgentRunEvents(runId, {
          lastEventId: fromEventId,
          signal: controller?.signal,
          onEnvelope: (envelope) =>
            handleRunEnvelope(envelope, {
              streamSessionId,
              streamGeneration: ctx.streamGeneration,
              isCurrentStream: ctx.isCurrentStream,
              finalizeSendSuccess: ctx.finalizeSendSuccess,
              restoreSendText: ctx.restoreSendText,
              removeTempMessage: ctx.removeTempMessage,
            }),
        });
      } catch (err: unknown) {
        if (!ctx.isCurrentStream()) return;
        const isAbort =
          (err instanceof DOMException && err.name === "AbortError") ||
          (typeof err === "object" &&
            err !== null &&
            "name" in err &&
            (err as { name: string }).name === "AbortError");
        if (isAbort) return;
        throw err;
      }
    },
    [handleRunEnvelope],
  );

  const sendRun = async ({ sessionId, snapshot, mode, onAccepted, onPostError }: SendRunOptions) => {
    const isComposer = mode === "composer";
    if (abortControllerRef.current) abortControllerRef.current.abort();
    invalidatePendingStreamingText();
    const streamGeneration = streamGenerationRef.current;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    if (isComposer) {
      savePromptDraftFor(sessionId, snapshot.rawText);
      saveImageDraftFor(sessionId, snapshot.rawText, snapshot.attachmentDrafts);
      setPromptInputLocal("");
      setLocalAttachments([]);
      setSelectedSkill(null);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
    onChatError(null);
    setHitlLinks([]);
    setIsStreaming(true);
    setStreamingText("");
    setStreamingToolCalls([]);
    setStreamingPhase("thinking");
    setStreamingIteration(null);

    const tempUserMsgId = `temp_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const tempUserMsg: AgentMessage = {
      message_id: tempUserMsgId,
      session_id: sessionId,
      sequence: messages.length + 1,
      role: "user",
      content: snapshot.content,
      attachments: snapshot.attachments.length > 0 ? snapshot.attachments : undefined,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    const removeTempMessage = () =>
      setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));

    const isCurrentStream = () =>
      streamGeneration === streamGenerationRef.current &&
      abortControllerRef.current === controller;
    // The composer stays usable while a run is streaming, so a newer draft may
    // exist by the time this send settles. Only touch the composer/drafts when
    // it is still empty; otherwise the next message would be lost.
    const composerIsEmpty = () =>
      inputTextRef.current.trim() === "" && pendingAttachmentsRef.current.length === 0;
    const finalizeSendSuccess = () => {
      if (!isComposer || !composerIsEmpty()) return;
      removePromptDraftFor(sessionId);
      removeImageDraftFor(sessionId);
      setPromptInputLocal("");
      setLocalAttachments([]);
    };
    const restoreSendText = () => {
      if (!isComposer || !composerIsEmpty()) return;
      savePromptDraftFor(sessionId, snapshot.rawText);
      setPromptInputLocal(snapshot.rawText);
      saveImageDraftFor(sessionId, snapshot.rawText, snapshot.attachmentDrafts);
      setLocalAttachments(snapshot.attachmentDrafts);
    };

    let runId: string;
    try {
      const started = await startAgentRun(
        sessionId,
        {
          content: snapshot.content,
          images: snapshot.attachments.length > 0 ? snapshot.attachments : undefined,
          slash_invocation: snapshot.slashInvocation,
        },
        snapshot.idempotencyKey,
      );
      if (!isCurrentStream()) {
        removeTempMessage();
        restoreSendText();
        return;
      }
      runId = started.run.run_id;
      onAccepted?.();
    } catch (err: unknown) {
      if (!isCurrentStream()) {
        removeTempMessage();
        restoreSendText();
        return;
      }
      if (!isComposer) {
        removeTempMessage();
        resetStreamingState();
        abortControllerRef.current = null;
        onPostError?.(err);
        return;
      }
      setSelectedSkill(snapshot.slashInvocation);
      restoreSendText();
      removeTempMessage();
      resetStreamingState();
      abortControllerRef.current = null;
      onChatError(getErrorMessage(err, "メッセージの送信に失敗しました。"));
      return;
    }

    try {
      await subscribeToAgentRun(runId, sessionId, 0, {
        streamGeneration,
        isCurrentStream,
        finalizeSendSuccess,
        restoreSendText,
        removeTempMessage,
      });
      if (isCurrentStream()) {
        // subscribeRunEvents returns after terminal or waiting_user pause.
        // If still streaming without terminal, reload to sync (e.g. waiting).
        const stillActive = activeRunIdRef.current === runId;
        if (stillActive) {
          // Terminal handlers already cleared activeRunId; if still set, the
          // stream paused (waiting_user) or closed early: sync detail.
          resetStreamingState();
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
          void loadSessionDetailRef.current(sessionId);
        }
      }
    } catch (err: unknown) {
      if (!isCurrentStream()) return;
      if (isAbortError(err)) {
        // Unmount/session-switch aborts only the subscription; run continues.
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      }
      if (isComposer) restoreSendText();
      removeTempMessage();
      resetStreamingState();
      abortControllerRef.current = null;
      activeRunIdRef.current = null;
      onChatError(getErrorMessage(err, "メッセージの送信に失敗しました。"));
    }
  };
  sendRunRef.current = sendRun;

  const flushQueue = useCallback(() => {
    if (flushInFlightRef.current || queueBlockedRef.current) return;
    const sessionId = selectedSessionIdRef.current;
    if (!sessionId) return;
    if (loadedSessionIdRef.current !== sessionId) return;
    if (isStreamingRef.current) return;
    if (activeWaitingRunRef.current) return;
    if (activeRunIdRef.current) return;
    if (runsRef.current.some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status))) return;
    const queue = queueRef.current;
    if (queue.sessionId !== sessionId || queue.items.length === 0) return;
    const head = queue.items[0];
    if (head.status !== "pending") return;
    flushInFlightRef.current = true;
    void sendRunRef
      .current({
        sessionId,
        snapshot: {
          content: head.content,
          rawText: head.content,
          attachments: head.attachments,
          attachmentDrafts: [],
          slashInvocation: head.slash_invocation,
          idempotencyKey: head.idempotency_key,
        },
        mode: "queue",
        onAccepted: () => {
          clearQueueRetry();
          updateQueueRef.current(sessionId, (items) =>
            removeQueuedAgentMessage(items, head.queue_id),
          );
        },
        onPostError: (error: unknown) => {
          const status = (error as { status?: number } | null)?.status;
          if (status === 409) {
            // Another run owns the session (e.g. another tab). Keep the item
            // pending, recover the active run, and retry after a short delay.
            // The terminal event of that run also releases the block.
            queueBlockedRef.current = true;
            void loadSessionDetailRef.current(sessionId).finally(() => {
              clearQueueRetry();
              queueRetryTimerRef.current = window.setTimeout(() => {
                queueRetryTimerRef.current = null;
                queueBlockedRef.current = false;
                flushQueueRef.current();
              }, 2000);
            });
            return;
          }
          const message =
            getErrorMessage(error, "メッセージの送信に失敗しました。");
          updateQueueRef.current(sessionId, (items) =>
            markQueuedAgentMessageError(items, head.queue_id, message),
          );
          onChatErrorRef.current(message);
        },
      })
      .finally(() => {
        flushInFlightRef.current = false;
      });
  }, [clearQueueRetry]);
  flushQueueRef.current = flushQueue;

  const submitMessageViaRun = async () => {
    if (!selectedSessionId) return;
    if (!inputText.trim() && pendingAttachments.length === 0 && !selectedSkill) return;
    const sessionId = selectedSessionId;
    const snapshot: AgentSendSnapshot = {
      content: inputText.trim(),
      rawText: inputText,
      attachments: pendingAttachments.map<AgentMessageAttachment>((att) => ({
        name: att.name,
        mime_type: att.mime_type,
        data: att.data,
      })),
      attachmentDrafts: pendingAttachments.map((att) => ({ ...att })),
      slashInvocation: selectedSkill,
      idempotencyKey: generateIdempotencyKey(),
    };

    const busy =
      isStreamingRef.current ||
      activeWaitingRunRef.current !== null ||
      runsRef.current.some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status)) ||
      (queueRef.current.sessionId === sessionId && queueRef.current.items.length > 0);
    if (busy) {
      const item = createQueuedMessage({
        content: snapshot.content,
        attachments: snapshot.attachments,
        slash_invocation: snapshot.slashInvocation,
      });
      const queued = updateQueueRef.current(sessionId, (items) =>
        enqueueAgentMessage(items, item),
      );
      if (queued !== "ok") {
        // Keep the composer so the message is not lost when it cannot persist.
        return;
      }
      removePromptDraftFor(sessionId);
      removeImageDraftFor(sessionId);
      setPromptInputLocal("");
      setLocalAttachments([]);
      setSelectedSkill(null);
      if (imageInputRef.current) imageInputRef.current.value = "";
      onChatError(null);
      flushQueue();
      return;
    }
    await sendRunRef.current({ sessionId, snapshot, mode: "composer" });
  };

  const handleRemoveQueuedMessage = useCallback((queueId: string) => {
    const sessionId = selectedSessionIdRef.current;
    if (!sessionId) return;
    updateQueueRef.current(sessionId, (items) => removeQueuedAgentMessage(items, queueId));
  }, []);

  const handleRetryQueuedMessage = useCallback(
    (queueId: string) => {
      const sessionId = selectedSessionIdRef.current;
      if (!sessionId) return;
      updateQueueRef.current(sessionId, (items) =>
        clearQueuedAgentMessageError(items, queueId),
      );
      queueBlockedRef.current = false;
      flushQueue();
    },
    [flushQueue],
  );

  // Flush the selected session's queue whenever the session becomes idle.
  // A stale active run is retried through the 409 path in flushQueue.
  useEffect(() => {
    if (isStreaming || activeWaitingRun || !selectedSessionId) return;
    if (loadedSessionId !== selectedSessionId) return;
    if (runs.some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status))) return;
    flushQueue();
  }, [
    flushQueue,
    isStreaming,
    activeWaitingRun,
    selectedSessionId,
    loadedSessionId,
    runs,
    queuedMessages,
  ]);

  const handleCancelAgentRun = useCallback(async () => {
    const runId = activeRunIdRef.current;
    if (!runId) return;
    try {
      await cancelAgentRun(runId);
    } catch (e) {
      onChatError(getErrorMessage(e, "キャンセルの送信に失敗しました。"));
    }
  }, [onChatError]);

  // Image attachment helpers
  const readFileAsDataUrl = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result;
        if (typeof result === "string") {
          resolve(result);
        } else {
          reject(new Error("ファイルの読み込みに失敗しました。"));
        }
      };
      reader.onerror = () => reject(new Error("ファイルの読み込みに失敗しました。"));
      reader.readAsDataURL(file);
    });

  const handleFilesSelected = async (files: FileList | File[] | null) => {
    if (!files || files.length === 0) return;
    const incoming = Array.from(files);
    const accepted: File[] = [];
    for (const file of incoming) {
      if (!file.type || !file.type.startsWith("image/")) {
        onChatError(`画像ファイル以外は添付できません: ${file.name || "ファイル"}`);
        continue;
      }
      if (file.size > MAX_AGENT_IMAGE_BYTES) {
        onChatError(
          `${file.name || "ファイル"} はサイズ上限(${Math.floor(MAX_AGENT_IMAGE_BYTES / (1024 * 1024))}MB)を超えています。`
        );
        continue;
      }
      accepted.push(file);
    }
    if (accepted.length === 0) return;
    const remainingSlots = MAX_AGENT_IMAGES - pendingAttachments.length;
    if (remainingSlots <= 0) {
      onChatError(`画像は最大${MAX_AGENT_IMAGES}枚まで添付できます。`);
      return;
    }
    const limited = accepted.slice(0, remainingSlots);
    if (accepted.length > limited.length) {
      onChatError(
        `画像は最大${MAX_AGENT_IMAGES}枚まで添付できます。超過分は無視されます。`
      );
    }
    setAttachmentReadsPending((count) => count + 1);
    void Promise.all(
      limited.map(async (file) => {
        try {
          const dataUrl = await readFileAsDataUrl(file);
          const base64 = dataUrl.includes(",") ? dataUrl.split(",")[1] : "";
          return {
            previewUrl: dataUrl,
            name: file.name || "image.png",
            mime_type: file.type,
            data: base64,
            size: file.size,
          } satisfies PendingAttachment;
        } catch {
          onChatError(`画像の読み込みに失敗しました: ${file.name || "ファイル"}`);
          return null;
        }
      })
    ).then((results) => {
      const valid = results.filter((r): r is PendingAttachment => r !== null);
      if (valid.length > 0) {
        setPendingAttachments((current) => [...current, ...valid]);
      }
      setAttachmentReadsPending((count) => Math.max(0, count - 1));
    });
  };

  const handleRemoveAttachment = (index: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleFormDragOver = (e: React.DragEvent<HTMLFormElement>) => {
    if (!activeAgent || !selectedSessionId) return;
    if (!e.dataTransfer.types.includes("Files")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setIsDragOver(true);
  };

  const handleFormDragLeave = (e: React.DragEvent<HTMLFormElement>) => {
    if (
      e.relatedTarget instanceof Node &&
      e.currentTarget.contains(e.relatedTarget)
    ) {
      return;
    }
    setIsDragOver(false);
  };

  const handleFormDrop = (e: React.DragEvent<HTMLFormElement>) => {
    if (!activeAgent || !selectedSessionId) return;
    if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
    e.preventDefault();
    setIsDragOver(false);
    void handleFilesSelected(e.dataTransfer.files);
  };

  const handleInputPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!activeAgent || !selectedSessionId) return;
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    const files: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind === "file" && item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length === 0) return;
    // Text in the same clipboard payload must survive: let the default paste
    // insert text while we only attach images.
    void handleFilesSelected(files);
  };

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      invalidatePendingStreamingText();
      if (queueRetryTimerRef.current !== null) {
        window.clearTimeout(queueRetryTimerRef.current);
        queueRetryTimerRef.current = null;
      }
    };
  }, [invalidatePendingStreamingText]);

  // Initial-load active-run restore: fold persisted events then follow live.
  // Server event log is the source of truth; sessionStorage is only a cache.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!selectedSessionId || loadedSessionId !== selectedSessionId) return;
    if (isStreaming || abortControllerRef.current || activeRunIdRef.current) return;
    const active = runs.find((r) =>
      ["queued", "running", "cancelling"].includes(r.status),
    );
    if (!active) return;
    const runId = active.run_id;
    const sessionIdAtResume = selectedSessionId;
    const cached = loadLastAppliedId("agent", runId);
    setIsStreaming(true);
    setStreamingText("");
    setStreamingToolCalls([]);
    setStreamingPhase("thinking");
    setStreamingIteration(null);
    onChatError(null);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const generation = streamGenerationRef.current;
    const isCurrent = () =>
      generation === streamGenerationRef.current &&
      abortControllerRef.current === controller &&
      // eslint-disable-next-line react-hooks/exhaustive-deps
      sessionIdAtResume === selectedSessionId;
    lastAppliedEventIdRef.current = cached;
    activeRunIdRef.current = runId;
    void (async () => {
      try {
        await subscribeAgentRunEvents(runId, {
          lastEventId: cached,
          signal: controller.signal,
          onEnvelope: (envelope) =>
            handleRunEnvelope(envelope, {
              streamSessionId: sessionIdAtResume,
              streamGeneration: generation,
              isCurrentStream: isCurrent,
              finalizeSendSuccess: () => {},
              restoreSendText: () => {},
            }),
        });
      } catch {
        // Abort or network: keep run alive; detail reload syncs state.
      } finally {
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
          setIsStreaming(false);
          setStreamingPhase(null);
          if (sessionIdAtResume === selectedSessionId) {
            void loadSessionDetail(sessionIdAtResume);
          }
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs, loadedSessionId, selectedSessionId]);

  let displayedStreamingPhase = streamingPhase;
  if (streamingToolCalls.some((toolCall) => toolCall.status === "running")) {
    displayedStreamingPhase = "tool_running";
  } else if (streamingToolCalls.some((toolCall) => toolCall.status === "preparing")) {
    displayedStreamingPhase = "tool_preparing";
  }

  return {
    isStreaming,
    streamingText,
    streamingToolCalls,
    streamingPhase,
    streamingIteration,
    displayedStreamingPhase,
    hitlLinks,
    setHitlLinks,
    copiedMessageId,
    selectedSkill,
    setSelectedSkill,
    pendingAttachments,
    attachmentReadsPending,
    isDragOver,
    setIsDragOver,
    queuedMessages,
    resetStreamingState,
    abortSubscriptionAndReset,
    handleRunEnvelope,
    submitMessageViaRun,
    handleRemoveQueuedMessage,
    handleRetryQueuedMessage,
    handleCancelAgentRun,
    handleFilesSelected,
    handleRemoveAttachment,
    handleFormDragOver,
    handleFormDragLeave,
    handleFormDrop,
    handleInputPaste,
    handleCopyMessage,
  };
}
