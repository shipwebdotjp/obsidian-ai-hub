import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
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

interface UseCodingRunStreamOptions {
  selectedSessionId: string | null;
  selectedSessionIdRef: MutableRefObject<string | null>;
  activeRun: CodingRun | null;
  latestRun: CodingRun | null;
  onError: (message: string | null) => void;
  loadSessionDetail: (sessionId: string) => Promise<void>;
  setMessages: React.Dispatch<React.SetStateAction<CodingMessage[]>>;
  setActiveRun: React.Dispatch<React.SetStateAction<CodingRun | null>>;
  setSessions: React.Dispatch<React.SetStateAction<CodingSession[]>>;
  setGitStatus: React.Dispatch<React.SetStateAction<GitStatus | null>>;
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
  onError,
  loadSessionDetail,
  setMessages,
  setActiveRun,
  setSessions,
  setGitStatus,
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
  const [workerState, setWorkerState] = useState<{
    status: "idle" | "running" | "done";
    attempt?: number;
    backend?: string;
    output?: string;
    error?: string | null;
  }>({ status: "idle" });

  // Reconnectable run subscription state (docs/run-sse).
  // AbortController here aborts only the subscription; it never cancels the run.
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const lastAppliedEventIdRef = useRef(0);

  // --- Reconnectable run subscription (docs/run-sse) ---
  // Server event log is the source of truth; sessionStorage caches only the
  // last applied event id. Abort here stops only the subscription, never the run.
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
        ctx.restoreSendText();
        if (!isCurrentSession) return;
        onError(String(data.message ?? "キャンセルされました"));
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      } else if (type === "error") {
        ctx.restoreSendText();
        if (!isCurrentSession) return;
        onError(String(data.message ?? "エラーが発生しました"));
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      } else if (type === "user_question") {
        ctx.finalizeSendSuccess();
        if (!isCurrentSession) return;
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
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
        ctx.finalizeSendSuccess();
        if (!isCurrentSession) return;
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
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
        setActivePhaseText(null);
        setWorkerState({
          status: "running",
          attempt: typeof data.attempt === "number" ? data.attempt : undefined,
          backend: typeof data.backend === "string" ? data.backend : undefined,
        });
      } else if (type === "worker_done") {
        const msg = asMessage((data as Record<string, unknown>).message);
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
    setIsStreaming(false);
    setActivePhaseText(null);
    setStreamingToolCalls([]);
    setWorkerState({ status: "idle" });
  };

  const executeSend = async () => {
    if (!selectedSessionId || !inputContent.trim() || isStreaming) return;

    const sendSessionId = selectedSessionId;
    const sendText = inputContent;
    const promptText = inputContent.trim();
    const currentSlashInv = slashInvocation;
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;
    const isCurrent = () =>
      selectedSessionIdRef.current === sendSessionId && abortControllerRef.current === controller;
    // 送信前のテキストは下書きとして確定保存する。入力欄だけ一時クリアし、
    // storage の削除は送信成功確定時まで行わない。
    savePromptDraftFor(sendSessionId, sendText);
    setPromptInputLocal("");
    setIsStreaming(true);
    setActivePhaseText("依頼を検討中...");
    setStreamingToolCalls([]);
    setWorkerState({ status: "idle" });
    onError(null);

    // 送信成功確定時のみ対象セッションの下書きを削除する。切替先にいる場合は
    // 入力状態へ触れず、対象セッションの storage のみ削除する。
    const finalizeSendSuccess = () => {
      removePromptDraftFor(sendSessionId);
      if (selectedSessionIdRef.current === sendSessionId) {
        setPromptInputLocal("");
      }
    };
    // 失敗・キャンセル時は送信前テキストを対象セッションの下書きへ戻す。
    // 切替先にいる場合は入力状態へ触れない。
    const restoreSendText = () => {
      savePromptDraftFor(sendSessionId, sendText);
      if (selectedSessionIdRef.current === sendSessionId) {
        setPromptInputLocal(sendText);
      }
    };

    // Optimistically add user message to list
    const tempUserMsgId = `temp_${Date.now()}`;
    const tempUserMsg: CodingMessage = {
      message_id: tempUserMsgId,
      session_id: sendSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: promptText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    const idempotencyKey =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let runId: string;
    try {
      const started = await startCodingRun(
        sendSessionId,
        promptText,
        idempotencyKey,
        currentSlashInv,
      );
      if (!isCurrent()) {
        // Switched sessions (or superseded) while start was in flight.
        // Streaming state belongs to the new session; only clean up this
        // send's optimistic message/draft and release refs if still ours.
        // The server run continues and resubscribes when returning to it.
        setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));
        restoreSendText();
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
        }
        return;
      }
      runId = started.run.run_id;
      setActiveRun(started.run);
      clearSlashInvocation();
    } catch (err: any) {
      if (!isCurrent()) {
        setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));
        restoreSendText();
        if (abortControllerRef.current === controller) {
          abortControllerRef.current = null;
          activeRunIdRef.current = null;
        }
        return;
      }
      onError(err.message || "メッセージの送信に失敗しました");
      restoreSendText();
      setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));
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
    workerState,
    abortControllerRef,
    activeRunIdRef,
    handleRunEnvelope,
    resetForSessionSwitch,
    executeSend,
    handleCancelRun,
  };
}
