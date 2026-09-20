import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
import { getErrorMessage } from "../../../utils/error";
import {
  cancelCodingRun,
  startCodingRun,
  subscribeCodingRunEvents,
  type CodingLiveToolCall,
  type CodingMessage,
  type CodingRun,
  type CodingSession,
  type GitStatus,
  type SlashInvocation,
} from "../../../api/coding";
import {
  loadLastAppliedId,
  saveLastAppliedId,
  type RunSseEnvelope,
} from "../../../api/runSse";
import type {
  ActiveWaitingRun,
  QuestionItem,
} from "../../../components/InConversationQuestionCard";
import {
  clearQueuedCodingMessageError,
  createQueuedCodingMessage,
  enqueueCodingMessage,
  markQueuedCodingMessageError,
  readCodingSendQueue,
  removeQueuedCodingMessage,
  writeCodingSendQueue,
  type CodingSendQueueWriteResult,
  type QueuedCodingMessage,
} from "../utils/codingSendQueue";

const NON_TERMINAL_RUN_STATUSES = new Set<CodingRun["status"]>([
  "queued",
  "running",
  "cancelling",
  "waiting_user",
]);

const EMPTY_RUNS: CodingRun[] = [];

function generateIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

interface CodingSendSnapshot {
  promptText: string;
  rawText: string;
  slashInvocation: SlashInvocation | null;
  idempotencyKey: string;
}

interface SendRunOptions {
  sessionId: string;
  snapshot: CodingSendSnapshot;
  mode: "composer" | "queue";
  onAccepted?: () => void;
  onPostError?: (error: unknown) => void;
}

/** Upsert a live ACP tool call emitted by the OpenCode worker. */
function upsertAcpToolCall(
  prev: CodingLiveToolCall[],
  data: Record<string, unknown>,
  type: string,
): CodingLiveToolCall[] {
  const toolCallId = String(data.tool_call_id ?? "");
  if (!toolCallId) return prev;
  const idx = prev.findIndex((tc) => tc.id === toolCallId);
  const existing = idx >= 0 ? prev[idx] : undefined;
  const rawStatus = String(data.status ?? "");
  // Unknown/missing status must not regress a terminal badge to running.
  const status: CodingLiveToolCall["status"] =
    rawStatus === "succeeded" ||
    rawStatus === "failed" ||
    rawStatus === "running" ||
    rawStatus === "preparing"
      ? rawStatus
      : existing?.status ?? "running";
  const incomingArgs =
    data.args && typeof data.args === "object"
      ? (data.args as Record<string, unknown>)
      : {};
  const inbound: CodingLiveToolCall = {
    id: toolCallId,
    tool_name: String(data.tool_name ?? ""),
    args: incomingArgs,
    result: type === "acp_tool_call_update" ? String(data.result ?? "") : "",
    status,
    error: (data.error as string | null) ?? null,
  };
  if (idx < 0) return [...prev, inbound];
  return prev.map((tc, i) =>
    i === idx
      ? {
          ...tc,
          tool_name: inbound.tool_name || tc.tool_name,
          args:
            type === "acp_tool_call_update" &&
            Object.keys(inbound.args).length === 0
              ? tc.args
              : inbound.args,
          result: inbound.result || tc.result,
          status: inbound.status,
          error: inbound.error ?? tc.error ?? null,
        }
      : tc,
  );
}

// Bound live text buffers so very long runs cannot accumulate MBs or reparse
// the entire accumulated Markdown on every delta.
const MAX_STREAM_CHARS = 200_000;

interface UseCodingRunStreamOptions {
  selectedSessionId: string | null;
  selectedSessionIdRef: MutableRefObject<string | null>;
  activeRun: CodingRun | null;
  latestRun: CodingRun | null;
  /** Session detail (active/latest run) is loaded for this session. */
  loadedSessionId: string | null;
  /** All known runs of the selected session's detail, if loaded. */
  sessionRuns?: CodingRun[];
  onError: (message: string | null) => void;
  loadSessionDetail: (sessionId: string) => Promise<void>;
  setMessages: React.Dispatch<React.SetStateAction<CodingMessage[]>>;
  setActiveRun: React.Dispatch<React.SetStateAction<CodingRun | null>>;
  setSessions: React.Dispatch<React.SetStateAction<CodingSession[]>>;
  setGitStatus: React.Dispatch<React.SetStateAction<GitStatus | null>>;
  activeWaitingRun: ActiveWaitingRun | null;
  setActiveWaitingRun: React.Dispatch<React.SetStateAction<ActiveWaitingRun | null>>;
  messages: CodingMessage[];
  inputContent: string;
  savePromptDraftFor: (sessionId: string, text: string) => void;
  setPromptInputLocal: (text: string) => void;
  removePromptDraftFor: (sessionId: string) => void;
  slashInvocation: SlashInvocation | null;
  clearSlashInvocation: () => void;
}

/** run 実行の SSE 購読・送信・キャンセルとストリーミング表示状態を管理する。 */
export function useCodingRunStream({
  selectedSessionId,
  selectedSessionIdRef,
  activeRun,
  latestRun,
  loadedSessionId,
  sessionRuns,
  onError,
  loadSessionDetail,
  setMessages,
  setActiveRun,
  setSessions,
  setGitStatus,
  activeWaitingRun,
  setActiveWaitingRun,
  messages,
  inputContent,
  savePromptDraftFor,
  setPromptInputLocal,
  removePromptDraftFor,
  slashInvocation,
  clearSlashInvocation,
}: UseCodingRunStreamOptions) {
  const [isStreaming, setIsStreaming] = useState(false);
  const [activePhaseText, setActivePhaseText] = useState<string | null>(null);
  const [streamingToolCalls, setStreamingToolCalls] = useState<CodingLiveToolCall[]>([]);
  // Live ACP worker output (separate from the Coordinator's tool calls).
  const [streamingText, setStreamingText] = useState("");
  const [streamingThought, setStreamingThought] = useState("");
  const [acpToolCalls, setAcpToolCalls] = useState<CodingLiveToolCall[]>([]);
  const [streamingPlan, setStreamingPlan] = useState<string[]>([]);
  const [workerState, setWorkerState] = useState<{
    status: "idle" | "running" | "done";
    attempt?: number;
    backend?: string;
    output?: string;
    error?: string | null;
  }>({ status: "idle" });
  const [queuedMessages, setQueuedMessages] = useState<QueuedCodingMessage[]>([]);

  // Send queue (sessionStorage). The ref is the flush source of truth; state
  // mirrors only the selected session for rendering.
  const queueRef = useRef<{ sessionId: string | null; items: QueuedCodingMessage[] }>({
    sessionId: null,
    items: [],
  });
  const flushInFlightRef = useRef(false);
  const queueBlockedRef = useRef(false);
  const queueRetryTimerRef = useRef<number | null>(null);
  const flushQueueRef = useRef<() => void>(() => {});
  const loadedSessionIdRef = useRef<string | null>(loadedSessionId);
  const activeWaitingRunRef = useRef<ActiveWaitingRun | null>(activeWaitingRun);
  const activeRunRef = useRef<CodingRun | null>(activeRun);
  const latestRunRef = useRef<CodingRun | null>(latestRun);
  const sessionRunsRef = useRef<CodingRun[]>(EMPTY_RUNS);
  const isStreamingRef = useRef(false);
  const updateQueueRef = useRef<
    (
      sessionId: string,
      updater: (items: QueuedCodingMessage[]) => QueuedCodingMessage[],
    ) => CodingSendQueueWriteResult
  >(() => "ok");
  const sendRunRef = useRef<(options: SendRunOptions) => Promise<void>>(async () => {});

  loadedSessionIdRef.current = loadedSessionId;
  activeWaitingRunRef.current = activeWaitingRun;
  activeRunRef.current = activeRun;
  latestRunRef.current = latestRun;
  sessionRunsRef.current = sessionRuns ?? EMPTY_RUNS;
  isStreamingRef.current = isStreaming;

  // Reconnectable run subscription state (docs/run-sse).
  // AbortController here aborts only the subscription; it never cancels the run.
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const lastAppliedEventIdRef = useRef(0);

  const clearQueueRetry = useCallback(() => {
    if (queueRetryTimerRef.current !== null) {
      window.clearTimeout(queueRetryTimerRef.current);
      queueRetryTimerRef.current = null;
    }
  }, []);

  const updateQueue = useCallback(
    (
      sessionId: string,
      updater: (items: QueuedCodingMessage[]) => QueuedCodingMessage[],
    ): CodingSendQueueWriteResult => {
      const current =
        queueRef.current.sessionId === sessionId
          ? queueRef.current.items
          : readCodingSendQueue(sessionId);
      const next = updater(current);
      const result = writeCodingSendQueue(sessionId, next);
      if (result !== "ok") {
        // Do not commit unpersisted state: a reload would restore the old queue
        // and the UI would diverge from storage.
        onError(
          result === "too-large"
            ? "待機メッセージが大きすぎて保存できません。"
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  updateQueueRef.current = updateQueue;

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
    const items = readCodingSendQueue(selectedSessionId);
    queueRef.current = { sessionId: selectedSessionId, items };
    setQueuedMessages(items);
  }, [selectedSessionId, clearQueueRetry]);

  // --- Reconnectable run subscription (docs/run-sse) ---
  // Server event log is the source of truth; sessionStorage caches only the
  // last applied event id. Abort here stops only the subscription, never the run.
  const clearAcpLiveDisplay = useCallback(() => {
    setStreamingText("");
    setStreamingThought("");
    setAcpToolCalls([]);
    setStreamingPlan([]);
  }, []);

  const handleRunEnvelope = useCallback(
    (
      envelope: RunSseEnvelope,
      ctx: {
        streamSessionId: string;
        finalizeSendSuccess: () => void;
        restoreSendText: () => void;
      },
    ) => {
      // At-least-once: ignore re-sent IDs. Track progress even when viewing
      // another session so a later resume can continue from the right cursor.
      if (envelope.eventId <= lastAppliedEventIdRef.current) return;
      lastAppliedEventIdRef.current = envelope.eventId;
      const runId = activeRunIdRef.current;
      if (runId) saveLastAppliedId("coding", runId, envelope.eventId);
      const isCurrentSession = selectedSessionIdRef.current === ctx.streamSessionId;

      const data = envelope.data as Record<string, unknown> & {
        event?: string;
        type?: string;
        phase?: "initial" | "review";
        call_key?: string;
        call_id?: string;
        tool_name?: string;
        args?: Record<string, unknown>;
        result?: string;
        status?: string;
        error?: string | null;
        message?: string;
        attempt?: number;
        backend?: string;
        prompt?: string;
        exit_code?: number;
        git_status?: GitStatus;
        session_title?: string;
        run_id?: string;
      };
      const type = String(data.event ?? data.type ?? "");
      const asMessage = (v: unknown): CodingMessage | null => {
        if (!v || typeof v !== "object") return null;
        const m = v as Record<string, unknown>;
        if (typeof m.message_id !== "string" || typeof m.content !== "string") return null;
        return v as CodingMessage;
      };
      if (type === "cancelled") {
        // Draft restore must happen even when switched (targets sendSessionId);
        // UI updates must not leak to the switched session.
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.restoreSendText();
        if (!isCurrentSession) return;
        onError(String(data.message ?? "キャンセルされました"));
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        clearAcpLiveDisplay();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      } else if (type === "error") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.restoreSendText();
        if (!isCurrentSession) return;
        onError(String(data.message ?? "エラーが発生しました"));
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        clearAcpLiveDisplay();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      } else if (type === "user_question") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.finalizeSendSuccess();
        if (!isCurrentSession) return;
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        clearAcpLiveDisplay();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        const hitlRunId = String(data.hitl_run_id ?? "");
        const questions = Array.isArray(data.questions)
          ? (data.questions as QuestionItem[])
          : [];
        if (hitlRunId) setActiveWaitingRun({ hitlRunId, questions, hitlStatus: "pending_user" });
        void loadSessionDetail(ctx.streamSessionId);
        return;
      } else if (type === "done") {
        queueBlockedRef.current = false;
        clearQueueRetry();
        ctx.finalizeSendSuccess();
        if (!isCurrentSession) return;
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        clearAcpLiveDisplay();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        if (data.git_status && typeof data.git_status === "object") {
          setGitStatus(data.git_status as GitStatus);
        }
        if (typeof data.session_title === "string" && data.session_title) {
          const newTitle = data.session_title;
          const sid = ctx.streamSessionId;
          setSessions((prev) => prev.map((s) => (s.session_id === sid ? { ...s, title: newTitle } : s)));
        }
        void loadSessionDetail(ctx.streamSessionId);
        return;
      }
      if (!isCurrentSession) return;
      if (type === "text_append") {
        const delta = String(data.delta ?? "");
        if (delta) setStreamingText((prev) => (prev + delta).slice(-MAX_STREAM_CHARS));
        return;
      } else if (type === "acp_thought_append") {
        const delta = String(data.delta ?? "");
        if (delta)
          setStreamingThought((prev) => (prev + delta).slice(-MAX_STREAM_CHARS));
        return;
      } else if (type === "acp_tool_call" || type === "acp_tool_call_update") {
        setAcpToolCalls((prev) => upsertAcpToolCall(prev, data, type));
        return;
      } else if (type === "acp_plan") {
        const rawEntries = Array.isArray(data.entries)
          ? (data.entries as unknown[])
          : [];
        setStreamingPlan(
          rawEntries.map((entry) =>
            typeof entry === "string" ? entry : JSON.stringify(entry),
          ),
        );
        return;
      }
      if (type === "orchestrator_start") {
        setActivePhaseText(data.phase === "review" ? "CLI結果を確認中..." : "依頼を検討中...");
      } else if (type === "orchestrator_tool_call_detected") {
        const callKey = String(data.call_key ?? "");
        const toolName = String(data.tool_name ?? "");
        if (!callKey || !toolName) return;
        setStreamingToolCalls((prev) => {
          if (prev.some((tc) => tc.call_key === callKey || tc.id === callKey)) return prev;
          return [
            ...prev,
            {
              id: callKey,
              call_key: callKey,
              tool_name: toolName,
              args: {},
              result: "",
              status: "preparing",
              phase: data.phase,
              phase_turn: typeof data.phase_turn === "number" ? (data.phase_turn as number) : undefined,
              iteration: typeof data.iteration === "number" ? (data.iteration as number) : undefined,
              call_index: typeof data.call_index === "number" ? (data.call_index as number) : undefined,
            },
          ];
        });
      } else if (type === "orchestrator_tool_call_start") {
        const callKey = String(data.call_key ?? "");
        const callId = String(data.call_id ?? "");
        const toolName = String(data.tool_name ?? "");
        if ((!callKey && !callId) || !toolName) return;
        setStreamingToolCalls((prev) => {
          const idx = prev.findIndex(
            (tc) => (callKey && (tc.call_key === callKey || tc.id === callKey)) || (callId && tc.call_id === callId),
          );
          const existing = idx >= 0 ? prev[idx] : undefined;
          const updated: CodingLiveToolCall = {
            id: existing?.id || callId || callKey,
            call_id: callId || existing?.call_id,
            call_key: callKey || existing?.call_key,
            tool_name: toolName,
            args: data.args ?? {},
            result: existing?.result || "",
            status: "running",
            phase: (data.phase as "initial" | "review") ?? existing?.phase,
            phase_turn: typeof data.phase_turn === "number" ? (data.phase_turn as number) : existing?.phase_turn,
            iteration: typeof data.iteration === "number" ? (data.iteration as number) : existing?.iteration,
            call_index: typeof data.call_index === "number" ? (data.call_index as number) : existing?.call_index,
          };
          if (idx >= 0) return prev.map((tc, i) => (i === idx ? updated : tc));
          return [...prev, updated];
        });
      } else if (type === "orchestrator_tool_call_end") {
        const callKey = String(data.call_key ?? "");
        const callId = String(data.call_id ?? "");
        if (!callKey && !callId) return;
        setStreamingToolCalls((prev) => {
          const idx = prev.findIndex(
            (tc) => (callId && (tc.call_id === callId || tc.id === callId)) || (callKey && (tc.call_key === callKey || tc.id === callKey)),
          );
          const status = (data.status === "failed" ? "failed" : "succeeded") as "succeeded" | "failed";
          if (idx >= 0) {
            return prev.map((tc, i) =>
              i === idx
                ? {
                    ...tc,
                    call_id: callId || tc.call_id,
                    call_key: callKey || tc.call_key,
                    tool_name: String(data.tool_name ?? tc.tool_name),
                    status,
                    result: String(data.result ?? ""),
                    error: (data.error as string | null) ?? null,
                    phase: (data.phase as "initial" | "review") ?? tc.phase,
                    phase_turn: typeof data.phase_turn === "number" ? (data.phase_turn as number) : tc.phase_turn,
                    iteration: typeof data.iteration === "number" ? (data.iteration as number) : tc.iteration,
                    call_index: typeof data.call_index === "number" ? (data.call_index as number) : tc.call_index,
                  }
                : tc,
            );
          }
          return [
            ...prev,
            {
              id: callId || callKey,
              call_id: callId || undefined,
              call_key: callKey || undefined,
              tool_name: String(data.tool_name ?? ""),
              args: {},
              result: String(data.result ?? ""),
              status,
              error: (data.error as string | null) ?? null,
              phase: data.phase,
              phase_turn: typeof data.phase_turn === "number" ? (data.phase_turn as number) : undefined,
              iteration: typeof data.iteration === "number" ? (data.iteration as number) : undefined,
              call_index: typeof data.call_index === "number" ? (data.call_index as number) : undefined,
            },
          ];
        });
      } else if (type === "orchestrator_message") {
        const msg = asMessage((data as Record<string, unknown>).message);
        setActivePhaseText(null);
        setStreamingToolCalls([]);
        if (msg) {
          setMessages((prev) => (prev.some((m) => m.message_id === msg.message_id) ? prev : [...prev, msg]));
        }
      } else if (type === "cli_request") {
        const msg = asMessage((data as Record<string, unknown>).message);
        if (msg) {
          setMessages((prev) => (prev.some((m) => m.message_id === msg.message_id) ? prev : [...prev, msg]));
        }
      } else if (type === "worker_start") {
        clearAcpLiveDisplay();
        setActivePhaseText(null);
        setWorkerState({
          status: "running",
          attempt: typeof data.attempt === "number" ? data.attempt : undefined,
          backend: typeof data.backend === "string" ? data.backend : undefined,
        });
      } else if (type === "worker_done") {
        const msg = asMessage((data as Record<string, unknown>).message);
        clearAcpLiveDisplay();
        setWorkerState({
          status: "done",
          attempt: typeof data.attempt === "number" ? data.attempt : undefined,
          output: msg ? msg.content : undefined,
          error: (data.error as string | null) ?? null,
        });
        if (data.git_status && typeof data.git_status === "object") {
          setGitStatus(data.git_status as GitStatus);
        }
        if (msg) {
          setMessages((prev) => (prev.some((m) => m.message_id === msg.message_id) ? prev : [...prev, msg]));
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // Initial-load active-run restore: fold persisted events then follow live.
  // Server event log is the source of truth; sessionStorage is only a cache.
  useEffect(() => {
    if (!selectedSessionId || !activeRun) return;
    if (isStreaming || abortControllerRef.current || activeRunIdRef.current) return;
    if (!["queued", "running", "cancelling"].includes(activeRun.status)) return;
    const runId = activeRun.run_id;
    const sessionIdAtResume = selectedSessionId;
    const cached = loadLastAppliedId("coding", runId);
    setIsStreaming(true);
    setActivePhaseText("依頼を検討中...");
    setStreamingToolCalls([]);
    setWorkerState({ status: "idle" });
    clearAcpLiveDisplay();
    onError(null);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    lastAppliedEventIdRef.current = cached;
    activeRunIdRef.current = runId;
    void (async () => {
      try {
        await subscribeCodingRunEvents(runId, {
          lastEventId: cached,
          signal: controller.signal,
          onEnvelope: (envelope) =>
            handleRunEnvelope(envelope, {
              streamSessionId: sessionIdAtResume,
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
          setActivePhaseText(null);
          if (selectedSessionIdRef.current === sessionIdAtResume) {
            void loadSessionDetail(sessionIdAtResume);
          }
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRun, selectedSessionId]);

  // Cleanup subscription on unmount (never cancels the run).
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      activeRunIdRef.current = null;
      if (queueRetryTimerRef.current !== null) {
        window.clearTimeout(queueRetryTimerRef.current);
        queueRetryTimerRef.current = null;
      }
    };
  }, []);

  /** セッション切替時に購読だけを破棄し、ストリーミング表示を初期化する。 */
  const resetForSessionSwitch = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    activeRunIdRef.current = null;
    lastAppliedEventIdRef.current = 0;
    flushInFlightRef.current = false;
    queueBlockedRef.current = false;
    setIsStreaming(false);
    setActivePhaseText(null);
    setStreamingToolCalls([]);
    setWorkerState({ status: "idle" });
    clearAcpLiveDisplay();
  };

  const sendRun = async ({
    sessionId: sendSessionId,
    snapshot,
    mode,
    onAccepted,
    onPostError,
  }: SendRunOptions) => {
    const isComposer = mode === "composer";
    const sendText = snapshot.rawText;
    const promptText = snapshot.promptText;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const isCurrent = () =>
      selectedSessionIdRef.current === sendSessionId && abortControllerRef.current === controller;
    // 送信前のテキストは下書きとして確定保存する。入力欄だけ一時クリアし、
    // storage の削除は送信成功確定時まで行わない。
    if (isComposer) {
      savePromptDraftFor(sendSessionId, sendText);
      setPromptInputLocal("");
    }
    setIsStreaming(true);
    setActivePhaseText("依頼を検討中...");
    setStreamingToolCalls([]);
    setWorkerState({ status: "idle" });
    clearAcpLiveDisplay();
    onError(null);

    // 送信成功確定時のみ対象セッションの下書きを削除する。切替先にいる場合は
    // 入力状態へ触れず、対象セッションの storage のみ削除する。
    const finalizeSendSuccess = () => {
      if (!isComposer) return;
      removePromptDraftFor(sendSessionId);
      if (selectedSessionIdRef.current === sendSessionId) {
        setPromptInputLocal("");
      }
    };
    // 失敗・キャンセル時は送信前テキストを対象セッションの下書きへ戻す。
    // 切替先にいる場合は入力状態へ触れない。
    const restoreSendText = () => {
      if (!isComposer) return;
      savePromptDraftFor(sendSessionId, sendText);
      if (selectedSessionIdRef.current === sendSessionId) {
        setPromptInputLocal(sendText);
      }
    };

    // Optimistically add user message to list
    const tempUserMsgId = `temp_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const tempUserMsg: CodingMessage = {
      message_id: tempUserMsgId,
      session_id: sendSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: promptText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    const removeTempMessage = () =>
      setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));

    let runId: string;
    try {
      const started = await startCodingRun(
        sendSessionId,
        promptText,
        snapshot.idempotencyKey,
        snapshot.slashInvocation,
      );
      if (!isCurrent()) {
        // Switched sessions (or superseded) while start was in flight.
        // Streaming state belongs to the new session; only clean up this
        // send's optimistic message/draft and release refs if still ours.
        // The server run continues and resubscribes when returning to it.
        removeTempMessage();
        restoreSendText();
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
        }
        return;
      }
      runId = started.run.run_id;
      setActiveRun(started.run);
      if (isComposer) clearSlashInvocation();
      onAccepted?.();
    } catch (err: any) {
      if (!isCurrent()) {
        removeTempMessage();
        restoreSendText();
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
        }
        return;
      }
      if (!isComposer) {
        removeTempMessage();
        setIsStreaming(false);
        setActivePhaseText(null);
        setStreamingToolCalls([]);
        setWorkerState({ status: "idle" });
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
        }
        onPostError?.(err);
        return;
      }
      onError(err.message || "メッセージの送信に失敗しました");
      restoreSendText();
      removeTempMessage();
      setIsStreaming(false);
      setActivePhaseText(null);
      setStreamingToolCalls([]);
      setWorkerState({ status: "idle" });
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
      }
      return;
    }

    // Immediately subscribe from 0 (server log has events between start and subscribe).
    lastAppliedEventIdRef.current = 0;
    activeRunIdRef.current = runId;
    try {
      await subscribeCodingRunEvents(runId, {
        lastEventId: 0,
        signal: controller.signal,
        onEnvelope: (envelope) =>
          handleRunEnvelope(envelope, {
            streamSessionId: sendSessionId,
            finalizeSendSuccess,
            restoreSendText,
          }),
      });
      if (isCurrent() && activeRunIdRef.current === runId) {
        // subscribeRunEvents returns after terminal or waiting pause.
        // Terminal handlers already cleared activeRunId; if still set, the
        // stream paused or closed early: sync detail.
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        setIsStreaming(false);
        setActivePhaseText(null);
        void loadSessionDetail(sendSessionId);
      }
    } catch (err: any) {
      if (!isCurrent()) return;
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (typeof err === "object" && err !== null && "name" in err && (err as { name: string }).name === "AbortError");
      if (isAbort) {
        // Unmount/session-switch aborts only the subscription; run continues.
        return;
      }
      onError(err.message || "メッセージの送信に失敗しました");
      restoreSendText();
      setIsStreaming(false);
      setActivePhaseText(null);
      setStreamingToolCalls([]);
      setWorkerState({ status: "idle" });
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
      }
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
    if (activeRunRef.current && NON_TERMINAL_RUN_STATUSES.has(activeRunRef.current.status)) {
      return;
    }
    if (latestRunRef.current && NON_TERMINAL_RUN_STATUSES.has(latestRunRef.current.status)) {
      return;
    }
    if (sessionRunsRef.current.some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status))) return;
    const queue = queueRef.current;
    if (queue.sessionId !== sessionId || queue.items.length === 0) return;
    const head = queue.items[0];
    if (head.status !== "pending") return;
    flushInFlightRef.current = true;
    void sendRunRef
      .current({
        sessionId,
        snapshot: {
          promptText: head.content,
          rawText: head.content,
          slashInvocation: head.slash_invocation,
          idempotencyKey: head.idempotency_key,
        },
        mode: "queue",
        onAccepted: () => {
          clearQueueRetry();
          updateQueueRef.current(sessionId, (items) =>
            removeQueuedCodingMessage(items, head.queue_id),
          );
        },
        onPostError: (error: unknown) => {
          const status = (error as { status?: number } | null)?.status;
          if (status === 409) {
            // Another run owns the session (e.g. another tab). Keep the item
            // pending, recover the active run, and retry after a short delay.
            // The terminal event of that run also releases the block.
            queueBlockedRef.current = true;
            void loadSessionDetail(sessionId).finally(() => {
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
            getErrorMessage(error, "メッセージの送信に失敗しました");
          updateQueueRef.current(sessionId, (items) =>
            markQueuedCodingMessageError(items, head.queue_id, message),
          );
          onError(message);
        },
      })
      .finally(() => {
        flushInFlightRef.current = false;
      });
  }, [clearQueueRetry, loadSessionDetail, onError]);
  flushQueueRef.current = flushQueue;

  const executeSend = async () => {
    if (!selectedSessionId) return;
    const promptText = inputContent.trim();
    if (!promptText && !slashInvocation) return;
    const sessionId = selectedSessionId;
    const snapshot: CodingSendSnapshot = {
      promptText,
      rawText: inputContent,
      slashInvocation,
      idempotencyKey: generateIdempotencyKey(),
    };

    const busy =
      isStreamingRef.current ||
      activeWaitingRunRef.current !== null ||
      (activeRunRef.current !== null &&
        NON_TERMINAL_RUN_STATUSES.has(activeRunRef.current.status)) ||
      (latestRunRef.current !== null &&
        NON_TERMINAL_RUN_STATUSES.has(latestRunRef.current.status)) ||
      sessionRunsRef.current.some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status)) ||
      (queueRef.current.sessionId === sessionId && queueRef.current.items.length > 0);
    if (busy) {
      const item = createQueuedCodingMessage({
        content: promptText,
        slash_invocation: slashInvocation,
      });
      const queued = updateQueueRef.current(sessionId, (items) =>
        enqueueCodingMessage(items, item),
      );
      if (queued !== "ok") {
        // Keep the composer so the message is not lost when it cannot persist.
        return;
      }
      removePromptDraftFor(sessionId);
      setPromptInputLocal("");
      clearSlashInvocation();
      onError(null);
      flushQueue();
      return;
    }
    await sendRunRef.current({ sessionId, snapshot, mode: "composer" });
  };

  const handleRemoveQueuedMessage = useCallback((queueId: string) => {
    const sessionId = selectedSessionIdRef.current;
    if (!sessionId) return;
    updateQueueRef.current(sessionId, (items) =>
      removeQueuedCodingMessage(items, queueId),
    );
  }, []);

  const handleRetryQueuedMessage = useCallback(
    (queueId: string) => {
      const sessionId = selectedSessionIdRef.current;
      if (!sessionId) return;
      updateQueueRef.current(sessionId, (items) =>
        clearQueuedCodingMessageError(items, queueId),
      );
      queueBlockedRef.current = false;
      flushQueue();
    },
    [flushQueue],
  );

  // Flush the selected session's queue whenever the session becomes idle.
  useEffect(() => {
    if (isStreaming || activeWaitingRun || !selectedSessionId) return;
    if (loadedSessionId !== selectedSessionId) return;
    if (activeRun && NON_TERMINAL_RUN_STATUSES.has(activeRun.status)) return;
    if (latestRun && NON_TERMINAL_RUN_STATUSES.has(latestRun.status)) return;
    if ((sessionRuns ?? EMPTY_RUNS).some((r) => NON_TERMINAL_RUN_STATUSES.has(r.status))) {
      return;
    }
    flushQueue();
  }, [
    flushQueue,
    isStreaming,
    activeWaitingRun,
    selectedSessionId,
    loadedSessionId,
    activeRun,
    latestRun,
    sessionRuns,
    queuedMessages,
  ]);

  const handleCancelRun = async () => {
    const isCancellable = (r: CodingRun | null | undefined) =>
      !!r && (r.status === "queued" || r.status === "running" || r.status === "cancelling");
    const runId =
      activeRunIdRef.current ||
      (isCancellable(activeRun) ? activeRun?.run_id : undefined) ||
      (isCancellable(latestRun) ? latestRun?.run_id : undefined);
    if (!runId) return;
    try {
      await cancelCodingRun(runId);
      if (selectedSessionId) {
        await loadSessionDetail(selectedSessionId);
      }
    } catch (err: any) {
      onError(err.message || "キャンセルの送信に失敗しました");
    }
  };

  return {
    isStreaming,
    activePhaseText,
    streamingToolCalls,
    streamingText,
    streamingThought,
    acpToolCalls,
    streamingPlan,
    workerState,
    queuedMessages,
    abortControllerRef,
    activeRunIdRef,
    handleRunEnvelope,
    resetForSessionSwitch,
    executeSend,
    handleRemoveQueuedMessage,
    handleRetryQueuedMessage,
    handleCancelRun,
  };
}
