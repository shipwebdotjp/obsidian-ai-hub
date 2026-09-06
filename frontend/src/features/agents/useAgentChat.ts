import { useCallback, useEffect, useRef, useState, type MutableRefObject } from "react";
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
  MAX_AGENT_IMAGES,
  MAX_AGENT_IMAGE_BYTES,
  matchesLiveToolCall,
  type PendingAttachment,
} from "./agentViewUtils";

interface UseAgentChatOptions {
  selectedSessionId: string | null;
  selectedAgentId: string | null;
  activeAgent: Agent | undefined;
  onChatError: (message: string | null) => void;
  loadSessions: (agentId: string) => Promise<void>;
  loadSessionDetail: (sessionId: string) => Promise<void>;
  messages: AgentMessage[];
  setMessages: React.Dispatch<React.SetStateAction<AgentMessage[]>>;
  runs: AgentRun[];
  loadedSessionId: string | null;
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
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);
  const [selectedSkill, setSelectedSkill] = useState<SlashInvocation | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentReadsPending, setAttachmentReadsPending] = useState(0);
  const [isDragOver, setIsDragOver] = useState(false);

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
        ctx.restoreSendText();
        ctx.removeTempMessage?.();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        onChatError(String(data.error ?? data.error_message ?? "エラーが発生しました。"));
      } else if (type === "cancelled") {
        ctx.restoreSendText();
        ctx.removeTempMessage?.();
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        onChatError("キャンセルされました");
      }
    },
    [
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

  const submitMessageViaRun = async () => {
    if (!selectedSessionId || (!inputText.trim() && pendingAttachments.length === 0 && !selectedSkill) || isStreaming)
      return;
    const streamSessionId = selectedSessionId;
    const userText = inputText.trim();
    const sendText = inputText;
    const attachmentsSnapshot = pendingAttachments.map<AgentMessageAttachment>((att) => ({
      name: att.name,
      mime_type: att.mime_type,
      data: att.data,
    }));
    const attachmentsSnapshotFull = pendingAttachments.map((att) => ({ ...att }));
    if (abortControllerRef.current) abortControllerRef.current.abort();
    invalidatePendingStreamingText();
    const streamGeneration = streamGenerationRef.current;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    savePromptDraftFor(streamSessionId, sendText);
    saveImageDraftFor(streamSessionId, sendText, attachmentsSnapshotFull);
    setPromptInputLocal("");
    setLocalAttachments([]);
    if (imageInputRef.current) imageInputRef.current.value = "";
    onChatError(null);
    setHitlLinks([]);
    setIsStreaming(true);
    setStreamingText("");
    setStreamingToolCalls([]);
    setStreamingPhase("thinking");
    setStreamingIteration(null);

    const tempUserMsgId = `temp_${Date.now()}`;
    const tempUserMsg: AgentMessage = {
      message_id: tempUserMsgId,
      session_id: streamSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: userText,
      attachments: attachmentsSnapshot.length > 0 ? attachmentsSnapshot : undefined,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    const removeTempMessage = () =>
      setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));

    const isCurrentStream = () =>
      streamGeneration === streamGenerationRef.current &&
      abortControllerRef.current === controller;
    const finalizeSendSuccess = () => {
      removePromptDraftFor(streamSessionId);
      removeImageDraftFor(streamSessionId);
      setPromptInputLocal("");
      setLocalAttachments([]);
    };
    const restoreSendText = () => {
      savePromptDraftFor(streamSessionId, sendText);
      setPromptInputLocal(sendText);
      saveImageDraftFor(streamSessionId, sendText, attachmentsSnapshotFull);
      setLocalAttachments(attachmentsSnapshotFull);
    };

    const idempotencyKey =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    let runId: string;
    const activeSkill = selectedSkill;
    setSelectedSkill(null);

    try {
      const started = await startAgentRun(
        streamSessionId,
        {
          content: userText,
          images: attachmentsSnapshot.length > 0 ? attachmentsSnapshot : undefined,
          slash_invocation: activeSkill,
        },
        idempotencyKey,
      );
      if (!isCurrentStream()) {
        removeTempMessage();
        restoreSendText();
        return;
      }
      runId = started.run.run_id;
    } catch (err: unknown) {
      setSelectedSkill(activeSkill);
      if (!isCurrentStream()) {
        removeTempMessage();
        restoreSendText();
        return;
      }
      restoreSendText();
      removeTempMessage();
      resetStreamingState();
      abortControllerRef.current = null;
      onChatError(err instanceof Error ? err.message : "メッセージの送信に失敗しました。");
      return;
    }

    try {
      await subscribeToAgentRun(runId, streamSessionId, 0, {
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
          void loadSessionDetail(streamSessionId);
        }
      }
    } catch (err: unknown) {
      if (!isCurrentStream()) return;
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (typeof err === "object" && err !== null && "name" in err && (err as { name: string }).name === "AbortError");
      if (isAbort) {
        // Unmount/session-switch aborts only the subscription; run continues.
        resetStreamingState();
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      }
      restoreSendText();
      removeTempMessage();
      resetStreamingState();
      abortControllerRef.current = null;
      activeRunIdRef.current = null;
      onChatError(err instanceof Error ? err.message : "メッセージの送信に失敗しました。");
    }
  };

  const handleCancelAgentRun = useCallback(async () => {
    const runId = activeRunIdRef.current;
    if (!runId) return;
    try {
      await cancelAgentRun(runId);
    } catch (e) {
      onChatError(e instanceof Error ? e.message : "キャンセルの送信に失敗しました。");
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
    if (!activeAgent || !selectedSessionId || isStreaming) return;
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
    if (!activeAgent || !selectedSessionId || isStreaming) return;
    if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) return;
    e.preventDefault();
    setIsDragOver(false);
    void handleFilesSelected(e.dataTransfer.files);
  };

  const handleInputPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (!activeAgent || !selectedSessionId || isStreaming) return;
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

  const handleCopyMessage = async (content: string, messageId: string) => {
    try {
      await navigator.clipboard.writeText(content);
      setCopiedMessageId(messageId);
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
      }
      copyResetRef.current = window.setTimeout(() => {
        setCopiedMessageId((current) => (current === messageId ? null : current));
        copyResetRef.current = null;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy message:", err);
    }
  };

  // Cleanup pending copy-feedback timer on unmount to avoid state updates
  // on an unmounted component.
  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
        copyResetRef.current = null;
      }
    };
  }, []);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      invalidatePendingStreamingText();
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
    resetStreamingState,
    abortSubscriptionAndReset,
    handleRunEnvelope,
    submitMessageViaRun,
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
