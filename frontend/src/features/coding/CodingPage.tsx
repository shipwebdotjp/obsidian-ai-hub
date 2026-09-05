import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  listCodingProjects,
  listCodingSessions,
  createCodingSession,
  getCodingSessionDetail,
  deleteCodingSession,
  cancelCodingRun,
  startCodingRun,
  subscribeCodingRunEvents,
  getGitStatus,
  getCodingDefaults,
  getCodingConfig,
  updateCodingDefaults,
  updateCodingSessionTools,
  updateCodingSessionTitle,
  getSlashCandidates,
  type SlashCandidate,
  type SlashInvocation,
  type CodingProjectItem,
  type CodingSession,
  type CodingMessage,
  type CodingRun,
  type GitStatus,
  type CodingTool,
  type CodingDefaults,
  type CodingSessionDetail,
  type CodingOrchestratorToolCall,
  type CodingLiveToolCall,
} from "../../api/coding";
import {
  loadLastAppliedId,
  saveLastAppliedId,
  type RunSseEnvelope,
} from "../../api/runSse";
import MarkdownPreview from "../../components/MarkdownPreview";
import { WaitingRunQuestionCard, WaitingRunStatusPanel, waitForHitlSettled, type ActiveWaitingRun, type QuestionItem, toQuestionItems } from "../../components/InConversationQuestionCard";
import { AnsweredRequirementCard } from "../../components/AnsweredRequirementCard";
import { getHitlRun, submitHitlAnswer, cancelHitlRun } from "../../api/client";
import { formatDateTime, formatYmdWithDow } from "../../utils/date";
import { useSessionPromptDraft } from "../../hooks/useSessionPromptDraft";
import {
  getChatInputPlaceholder,
  shouldSendOnEnter,
  useChatSendMode,
} from "../settings/chatSendMode";
import { ChevronLeft, ChevronRight } from "lucide-react";

export default function CodingPage() {
  const [projects, setProjects] = useState<CodingProjectItem[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const [sessionDetail, setSessionDetail] = useState<CodingSessionDetail | null>(null);
  const [messages, setMessages] = useState<CodingMessage[]>([]);
  const [activeRun, setActiveRun] = useState<CodingRun | null>(null);
  const [latestRun, setLatestRun] = useState<CodingRun | null>(null);
  const [activeWaitingRun, setActiveWaitingRun] = useState<ActiveWaitingRun | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);

  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Desktop left pane collapse & mobile drawer state
  const [leftPaneCollapsed, setLeftPaneCollapsed] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const drawerCloseBtnRef = useRef<HTMLButtonElement>(null);
  const drawerTriggerBtnRef = useRef<HTMLButtonElement>(null);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);

  // New session modal state
  const [isNewSessionModalOpen, setIsNewSessionModalOpen] = useState(false);
  const [newSessionBackend, setNewSessionBackend] = useState<"codex" | "opencode">("opencode");
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [creatingSession, setCreatingSession] = useState(false);
  const backendManuallySelected = useRef(false);

  // Conversation tool settings modal state
  const [isSessionSettingsOpen, setIsSessionSettingsOpen] = useState(false);
  const [sessionSelectedTools, setSessionSelectedTools] = useState<string[]>([]);
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [savingSessionTools, setSavingSessionTools] = useState(false);

  // User default tool settings modal state
  const [isUserDefaultsOpen, setIsUserDefaultsOpen] = useState(false);
  const [userDefaults, setUserDefaults] = useState<CodingDefaults | null>(null);
  const [userDefaultsSelectedTools, setUserDefaultsSelectedTools] = useState<string[]>([]);
  const [loadingUserDefaults, setLoadingUserDefaults] = useState(false);
  const [savingUserDefaults, setSavingUserDefaults] = useState(false);

  // Chat input and streaming state
  // プロンプト下書きはセッションごとに sessionStorage へデバウンス保存・復元する。
  const {
    draft: inputContent,
    setDraft: setInputContent,
    setLocalDraft: setPromptInputLocal,
    saveDraftFor: savePromptDraftFor,
    removeDraftFor: removePromptDraftFor,
  } = useSessionPromptDraft("coding", selectedSessionId);
  // 非同期の送信完了・失敗処理が、切替先セッションの入力・下書きへ波及しない
  // よう、現在選択中セッションを ref で追跡する。
  const selectedSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);
  // Reconnectable run subscription state (docs/run-sse).
  // AbortController here aborts only the subscription; it never cancels the run.
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const lastAppliedEventIdRef = useRef(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const [chatSendMode] = useChatSendMode();
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

  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);

  // Slash invocation candidate state
  const [slashInvocation, setSlashInvocation] = useState<SlashInvocation | null>(null);
  const [slashCandidates, setSlashCandidates] = useState<SlashCandidate[]>([]);
  const [hasSkillsTool, setHasSkillsTool] = useState(true);
  const [slashPaletteIndex, setSlashPaletteIndex] = useState(0);

  const messageEndRef = useRef<HTMLDivElement>(null);

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

  useEffect(() => {
    return () => {
      if (copyResetRef.current !== null) {
        window.clearTimeout(copyResetRef.current);
        copyResetRef.current = null;
      }
    };
  }, []);

  // Auto-scroll on new messages / phase change / waiting-run change
  useEffect(() => {
    if (typeof messageEndRef.current?.scrollIntoView === "function") {
      messageEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, activePhaseText, streamingToolCalls, workerState, activeWaitingRun]);

  const toolCallsByMessageId = useMemo(() => {
    const map = new Map<string, CodingOrchestratorToolCall[]>();
    if (!sessionDetail?.orchestrator_tool_calls) return map;
    for (const tc of sessionDetail.orchestrator_tool_calls) {
      if (tc.orchestrator_message_id) {
        const list = map.get(tc.orchestrator_message_id) || [];
        list.push(tc);
        map.set(tc.orchestrator_message_id, list);
      }
    }
    return map;
  }, [sessionDetail?.orchestrator_tool_calls]);

  const unassociatedToolCallsByRunId = useMemo(() => {
    const map = new Map<string, CodingOrchestratorToolCall[]>();
    if (!sessionDetail?.orchestrator_tool_calls) return map;
    for (const tc of sessionDetail.orchestrator_tool_calls) {
      if (!tc.orchestrator_message_id && tc.run_id) {
        const list = map.get(tc.run_id) || [];
        list.push(tc);
        map.set(tc.run_id, list);
      }
    }
    return map;
  }, [sessionDetail?.orchestrator_tool_calls]);

  const getRunIdForUserMessage = (msg: CodingMessage): string | null => {
    if (msg.run_id) return msg.run_id;
    if (activeRun && activeRun.user_message_id === msg.message_id) return activeRun.run_id;
    if (latestRun && latestRun.user_message_id === msg.message_id) return latestRun.run_id;
    return null;
  };

  const runById = useMemo(() => {
    const m = new Map<string, CodingRun>();
    for (const r of sessionDetail?.runs ?? []) m.set(r.run_id, r);
    if (activeRun) m.set(activeRun.run_id, activeRun);
    if (latestRun) m.set(latestRun.run_id, latestRun);
    return m;
  }, [sessionDetail?.runs, activeRun, latestRun]);

  // Mobile drawer focus management & trap
  useEffect(() => {
    if (mobileDrawerOpen) {
      drawerCloseBtnRef.current?.focus();

      const drawer = mobileDrawerRef.current;
      if (!drawer) return;

      const focusableSelector =
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      const onKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          setMobileDrawerOpen(false);
          return;
        }
        if (e.key !== "Tab") return;
        const focusable = Array.from(
          drawer.querySelectorAll<HTMLElement>(focusableSelector)
        ).filter((el) => !el.hasAttribute("disabled") && el.offsetParent !== null);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      };
      window.addEventListener("keydown", onKeyDown);
      return () => {
        window.removeEventListener("keydown", onKeyDown);
        drawerTriggerBtnRef.current?.focus();
      };
    }
  }, [mobileDrawerOpen]);

  // Load projects on mount
  useEffect(() => {
    loadProjects();
  }, []);

  // Fetch default backend from server config (fallback opencode, preserve manual selection)
  useEffect(() => {
    let cancelled = false;
    const fetchDefaultBackend = async () => {
      try {
        const cfg = await getCodingConfig();
        const backend = cfg.default_backend;
        if (!cancelled && !backendManuallySelected.current && (backend === "codex" || backend === "opencode")) {
          setNewSessionBackend(backend);
        }
      } catch {
        if (!cancelled && !backendManuallySelected.current) {
          setNewSessionBackend("opencode");
        }
      }
    };
    fetchDefaultBackend();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadProjects = async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const data = await listCodingProjects();
      setProjects(data);
      const valid = data.filter((item) => item.is_valid_git_repo === true);
      if (valid.length > 0) {
        if (selectedProjectId === null || !valid.some((v) => v.project.project_id === selectedProjectId)) {
          setSelectedProjectId(valid[0].project.project_id);
        }
      } else {
        setSelectedProjectId(null);
      }
    } catch (e: any) {
      setError(e.message || "プロジェクト一覧の取得に失敗しました");
    } finally {
      setLoadingProjects(false);
    }
  };

  const syncSessionUrl = useCallback(
    (sessionId: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (sessionId) {
            next.set("session_id", sessionId);
          } else {
            next.delete("session_id");
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const selectSession = useCallback(
    (sessionId: string | null) => {
      setSelectedSessionId(sessionId);
      syncSessionUrl(sessionId);
    },
    [syncSessionUrl],
  );

  // Load sessions when selected project changes
  useEffect(() => {
    if (selectedProjectId === null) {
      setSessions([]);
      setSelectedSessionId(null);
      return;
    }
    loadSessions(selectedProjectId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId]);

  const loadSessions = async (projectId: number) => {
    setLoadingSessions(true);
    try {
      const data = await listCodingSessions(projectId);
      setSessions(data);
      if (data.length > 0) {
        const urlSessionId = searchParams.get("session_id");
        if (urlSessionId && data.some((s) => s.session_id === urlSessionId)) {
          setSelectedSessionId(urlSessionId);
        } else {
          const fallback = data[0].session_id;
          setSelectedSessionId(fallback);
          if (urlSessionId && !data.some((s) => s.session_id === urlSessionId)) {
            // Stale deep link: drop it so back-navigation does not re-select it.
            syncSessionUrl(null);
          } else if (!urlSessionId) {
            syncSessionUrl(fallback);
          }
        }
      } else {
        setSelectedSessionId(null);
        syncSessionUrl(null);
        setMessages([]);
        setActiveRun(null);
        setLatestRun(null);
      }
    } catch (e: any) {
      setError(e.message || "セッション一覧の取得に失敗しました");
    } finally {
      setLoadingSessions(false);
    }
  };

  // Load messages & run details when selected session changes.
  // Subscription-only abort: switching sessions never cancels the run.
  useEffect(() => {
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
    setGitStatus(null);
    setSlashInvocation(null);
    if (!selectedSessionId) {
      setMessages([]);
      setActiveRun(null);
      setLatestRun(null);
      setSlashCandidates([]);
      setHasSkillsTool(true);
      return;
    }
    loadSessionDetail(selectedSessionId);
    const requestSessionId = selectedSessionId;
    getSlashCandidates(requestSessionId)
      .then((res) => {
        if (selectedSessionIdRef.current !== requestSessionId) return;
        setSlashCandidates(res.candidates);
        setHasSkillsTool(res.has_skills_tool);
      })
      .catch(() => {
        if (selectedSessionIdRef.current !== requestSessionId) return;
        setSlashCandidates([]);
        setHasSkillsTool(true);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSessionId]);

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

  const fetchGitStatus = async (repoPath: string, targetSessionId: string) => {
    try {
      const status = await getGitStatus(repoPath);
      if (selectedSessionId === targetSessionId) {
        setGitStatus(status);
      }
    } catch (_) {
      if (selectedSessionId === targetSessionId) {
        setGitStatus(null);
      }
    }
  };

  const loadSessionDetail = async (sessionId: string) => {
    setLoadingMessages(true);
    try {
      const data = await getCodingSessionDetail(sessionId);
      setSessionDetail(data);
      setMessages(data.messages);
      setActiveRun(data.active_run);
      const lRun = data.latest_run;
      setLatestRun(lRun);
      setSessionSelectedTools(data.effective_tool_ids);

      // Check if latest run is waiting_user and fetch its active question set
      if (lRun && lRun.status === "waiting_user" && lRun.hitl_run_id) {
        try {
          const hitlDetail = await getHitlRun(lRun.hitl_run_id);
          setActiveWaitingRun({
            hitlRunId: lRun.hitl_run_id,
            questions: toQuestionItems(hitlDetail.questions || []),
            hitlStatus: (hitlDetail.status as string | null) ?? null,
            hitlError: (hitlDetail.error_message as string | null) ?? null,
          });
        } catch (e) {
          console.error("Failed to load HITL run:", e);
          setActiveWaitingRun(null);
          setError("質問の取得に失敗しました。再読み込みしてください。");
        }
      } else {
        setActiveWaitingRun(null);
      }
      if (data.session.repo_path) {
        fetchGitStatus(data.session.repo_path, sessionId);
      } else {
        setGitStatus(null);
      }
    } catch (e: any) {
      setSessionDetail(null);
      setGitStatus(null);
      setError(e.message || "セッション詳細の取得に失敗しました");
    } finally {
      setLoadingMessages(false);
    }
  };

  // Submit answers sequentially so a partial failure surfaces instead of
  // silently leaving questions pending. Skip state updates when the selection
  // moved to another session mid-operation (its own detail load owns the UI).
  const handleSubmitWaitingAnswers = async (
    waiting: ActiveWaitingRun,
    answers: Record<string, { value: string; comment?: string }>,
  ) => {
    const opSessionId = selectedSessionId;
    const opHitlRunId = waiting.hitlRunId;
    try {
      for (const [qKey, ans] of Object.entries(answers)) {
        await submitHitlAnswer(opHitlRunId, qKey, ans.value, ans.comment);
      }
      if (selectedSessionIdRef.current !== opSessionId) return;
      // Switch to the resume-pending panel immediately so the answered
      // choices never linger as an empty card frame.
      setActiveWaitingRun({ hitlRunId: opHitlRunId, questions: [], hitlStatus: "ready_to_resume" });
      // Wait for HITL dispatch to settle before reloading; the active-run
      // restore effect then resubscribes the same run ID from the existing
      // event cursor, replaying user_question then post-resume events in order.
      const settled = await waitForHitlSettled(opHitlRunId);
      if (selectedSessionIdRef.current !== opSessionId) return;
      if (settled) {
        setActiveWaitingRun((prev) =>
          prev && prev.hitlRunId === opHitlRunId
            ? { hitlRunId: opHitlRunId, questions: [], hitlStatus: settled.status }
            : prev,
        );
      }
      if (opSessionId) {
        await loadSessionDetail(opSessionId);
      }
    } catch (e: any) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      setError(e.message || "回答の送信に失敗しました");
    }
  };

  const handleCancelWaitingRun = async (waiting: ActiveWaitingRun) => {
    const opSessionId = selectedSessionId;
    try {
      await cancelHitlRun(waiting.hitlRunId);
      if (selectedSessionIdRef.current !== opSessionId) return;
      setActiveWaitingRun(null);
      if (opSessionId) {
        await loadSessionDetail(opSessionId);
      }
    } catch (e: any) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      setError(e.message || "質問の取消に失敗しました");
    }
  };

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
        setError(String(data.message ?? "キャンセルされました"));
        setIsStreaming(false);
        setActivePhaseText(null);
        setWorkerState({ status: "idle" });
        abortControllerRef.current = null;
        activeRunIdRef.current = null;
        return;
      } else if (type === "error") {
        ctx.restoreSendText();
        if (!isCurrentSession) return;
        setError(String(data.message ?? "エラーが発生しました"));
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
    setError(null);
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

  const refreshSlashCandidates = async (sessionId: string) => {
    try {
      const res = await getSlashCandidates(sessionId);
      if (selectedSessionIdRef.current !== sessionId) return;
      setSlashCandidates(res.candidates);
      setHasSkillsTool(res.has_skills_tool);
      if (!res.has_skills_tool) setSlashInvocation(null);
    } catch {
      if (selectedSessionIdRef.current !== sessionId) return;
      setSlashCandidates([]);
      setHasSkillsTool(true);
    }
  };

  const handleSaveSessionTools = async () => {
    if (!selectedSessionId) return;
    const opSessionId = selectedSessionId;
    const trimmedTitle = sessionTitleDraft.trim();
    if (!trimmedTitle) {
      setError("セッションタイトルを入力してください");
      return;
    }
    setSavingSessionTools(true);
    try {
      const currentTitle = sessionDetail?.session.title ?? selectedSession?.title ?? "";
      if (trimmedTitle !== currentTitle) {
        try {
          const titled = await updateCodingSessionTitle(opSessionId, trimmedTitle);
          if (selectedSessionIdRef.current !== opSessionId) return;
          setSessionDetail(titled);
          setSessionSelectedTools(titled.effective_tool_ids);
          setSessions((prev) =>
            prev.map((s) => (s.session_id === opSessionId ? { ...s, title: titled.session.title } : s)),
          );
        } catch (e: any) {
          if (selectedSessionIdRef.current !== opSessionId) return;
          setError(e.message || "セッションタイトルの保存に失敗しました");
          return;
        }
      }
      const updated = await updateCodingSessionTools(opSessionId, sessionSelectedTools);
      if (selectedSessionIdRef.current !== opSessionId) return;
      setSessionDetail(updated);
      setSessionSelectedTools(updated.effective_tool_ids);
      setSessions((prev) =>
        prev.map((s) => (s.session_id === opSessionId ? { ...s, title: updated.session.title } : s)),
      );
      setIsSessionSettingsOpen(false);
      await refreshSlashCandidates(opSessionId);
    } catch (e: any) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      setError(e.message || "会話ツールの保存に失敗しました");
    } finally {
      setSavingSessionTools(false);
    }
  };

  const handleResetSessionTools = async () => {
    if (!selectedSessionId) return;
    const opSessionId = selectedSessionId;
    setSavingSessionTools(true);
    try {
      const updated = await updateCodingSessionTools(opSessionId, null);
      if (selectedSessionIdRef.current !== opSessionId) return;
      setSessionDetail(updated);
      setSessionSelectedTools(updated.effective_tool_ids);
      setSessions((prev) =>
        prev.map((s) => (s.session_id === opSessionId ? { ...s, title: updated.session.title } : s)),
      );
      setIsSessionSettingsOpen(false);
      await refreshSlashCandidates(opSessionId);
    } catch (e: any) {
      setError(e.message || "会話ツールのリセットに失敗しました");
    } finally {
      setSavingSessionTools(false);
    }
  };

  const handleOpenUserDefaults = async () => {
    setIsUserDefaultsOpen(true);
    setLoadingUserDefaults(true);
    setUserDefaults(null);
    setUserDefaultsSelectedTools([]);
    try {
      const data = await getCodingDefaults();
      setUserDefaults(data);
      setUserDefaultsSelectedTools(data.default_tool_ids);
    } catch (e: any) {
      setUserDefaults(null);
      setUserDefaultsSelectedTools([]);
      setError(e.message || "ユーザー既定値の取得に失敗しました");
    } finally {
      setLoadingUserDefaults(false);
    }
  };

  const handleSaveUserDefaults = async () => {
    setSavingUserDefaults(true);
    try {
      const updated = await updateCodingDefaults(userDefaultsSelectedTools);
      setUserDefaults(updated);
      setIsUserDefaultsOpen(false);
      if (selectedSessionId) {
        await loadSessionDetail(selectedSessionId);
      }
    } catch (e: any) {
      setError(e.message || "ユーザー既定値の保存に失敗しました");
    } finally {
      setSavingUserDefaults(false);
    }
  };

  const handleCreateSession = async () => {
    if (selectedProjectId === null) return;
    setCreatingSession(true);
    try {
      const session = await createCodingSession(
        selectedProjectId,
        newSessionBackend,
        newSessionTitle.trim() || undefined,
      );
      setIsNewSessionModalOpen(false);
      setNewSessionTitle("");
      await loadSessions(selectedProjectId);
      selectSession(session.session_id);
    } catch (e: any) {
      setError(e.message || "セッションの作成に失敗しました");
    } finally {
      setCreatingSession(false);
    }
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("このセッションを削除してもよろしいですか？")) return;
    try {
      await deleteCodingSession(sessionId);
      if (selectedProjectId) {
        await loadSessions(selectedProjectId);
      }
    } catch (err: any) {
      setError(err.message || "セッションの削除に失敗しました");
    }
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
    setError(null);

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
      if (!isCurrent()) return;
      runId = started.run.run_id;
      setActiveRun(started.run);
      setSlashInvocation(null);
    } catch (err: any) {
      if (!isCurrent()) return;
      setError(err.message || "メッセージの送信に失敗しました");
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
      setError(err.message || "メッセージの送信に失敗しました");
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

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeSend();
  };

  const slashQuery = useMemo(() => {
    if (slashInvocation) return null;
    return inputContent.startsWith("/") ? inputContent.slice(1) : null;
  }, [inputContent, slashInvocation]);

  const filteredCandidates = useMemo(() => {
    if (slashQuery === null) return [];
    const q = slashQuery.toLowerCase();
    return slashCandidates.filter((c) => c.name.toLowerCase().includes(q));
  }, [slashCandidates, slashQuery]);

  const showSlashPalette = slashQuery !== null;

  useEffect(() => {
    setSlashPaletteIndex(0);
  }, [slashQuery, slashCandidates]);

  const handleSelectCandidate = (cand: SlashCandidate) => {
    setSlashInvocation({ kind: "skill", name: cand.name });
    setInputContent("");
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showSlashPalette) {
      if (e.key === "Escape") {
        e.preventDefault();
        setInputContent("");
        return;
      }
      if (hasSkillsTool && filteredCandidates.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSlashPaletteIndex((prev) => (prev + 1) % filteredCandidates.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSlashPaletteIndex((prev) => (prev - 1 + filteredCandidates.length) % filteredCandidates.length);
          return;
        }
        if (e.key === "Enter") {
          e.preventDefault();
          const selected = filteredCandidates[slashPaletteIndex];
          if (selected) {
            handleSelectCandidate(selected);
          }
          return;
        }
      }
    }

    if (shouldSendOnEnter(e, chatSendMode)) {
      e.preventDefault();
      void executeSend();
    }
  };

  const codingPlaceholder = getChatInputPlaceholder(chatSendMode, "指示・質問を入力");

  const handleCancelRun = async () => {
    const runId = activeRunIdRef.current || activeRun?.run_id || latestRun?.run_id;
    if (!runId) return;
    try {
      await cancelCodingRun(runId);
      if (selectedSessionId) {
        await loadSessionDetail(selectedSessionId);
      }
    } catch (err: any) {
      setError(err.message || "キャンセルの送信に失敗しました");
    }
  };

  const validProjects = projects.filter((p) => p.is_valid_git_repo === true);
  const selectedProjectItem = validProjects.find(
    (p) => p.project.project_id === selectedProjectId,
  );
  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);

  const currentRun = activeRun || latestRun;

  return (
    <div className="flex h-full w-full overflow-hidden bg-slate-50">
      {/* Mobile Drawer Overlay */}
      {mobileDrawerOpen && (
        <div
          ref={mobileDrawerRef}
          className="fixed inset-0 z-50 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="プロジェクトとセッションの選択"
        >
          <div className="flex h-full w-80 max-w-[85vw] flex-col border-r border-slate-200 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50">
              <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                プロジェクト & セッション
              </h2>
              <button
                ref={drawerCloseBtnRef}
                type="button"
                onClick={() => setMobileDrawerOpen(false)}
                className="rounded p-1 text-slate-500 hover:bg-slate-200 cursor-pointer"
                aria-label="サイドバーを閉じる"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-slate-200">
              {/* Mobile Project Selector Section */}
              <div className="p-3">
                <div className="mb-2 text-[11px] font-semibold text-slate-500 uppercase">
                  プロジェクト選択
                </div>
                {loadingProjects ? (
                  <div className="p-2 text-xs text-slate-500">読み込み中...</div>
                ) : validProjects.length === 0 ? (
                  <div className="p-2 text-xs text-slate-500">プロジェクトがありません</div>
                ) : (
                  <div className="space-y-1">
                    {validProjects.map((item) => {
                      const isSelected = item.project.project_id === selectedProjectId;
                      return (
                        <button
                          key={item.project.project_id}
                          type="button"
                          onClick={() => {
                            setSelectedProjectId(item.project.project_id);
                          }}
                          className={`w-full rounded px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                            isSelected
                              ? "bg-slate-900 font-medium text-white"
                              : "text-slate-700 hover:bg-slate-100"
                          }`}
                        >
                          <span className="truncate">{item.project.display_name}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Mobile Sessions Section */}
              <div className="p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">
                    セッション一覧
                  </span>
                  {selectedProjectItem && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsNewSessionModalOpen(true);
                        setMobileDrawerOpen(false);
                      }}
                      className="rounded bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-slate-800 cursor-pointer"
                    >
                      + 新規
                    </button>
                  )}
                </div>

                {loadingSessions ? (
                  <div className="p-2 text-xs text-slate-500">セッション読み込み中...</div>
                ) : sessions.length === 0 ? (
                  <div className="p-2 text-xs text-slate-500">セッションがありません</div>
                ) : (
                  <div className="space-y-1">
                    {sessions.map((sess) => {
                      const isSelected = sess.session_id === selectedSessionId;
                      return (
                        <button
                          key={sess.session_id}
                          type="button"
                          data-testid="memory-row"
                          data-selected={isSelected}
                          onClick={() => {
                            selectSession(sess.session_id);
                            setMobileDrawerOpen(false);
                          }}
                          className={`w-full flex cursor-pointer items-center justify-between rounded px-2.5 py-2 text-left text-xs transition-colors ${
                            isSelected
                              ? "bg-slate-200 border-l-4 border-slate-800 font-medium text-slate-900"
                              : "text-slate-700 hover:bg-slate-50"
                          }`}
                        >
                          <div className="min-w-0 flex-1 truncate">{sess.title}</div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
          <button
            type="button"
            aria-label="オーバーレイを閉じる"
            onClick={() => setMobileDrawerOpen(false)}
            className="flex-1 bg-slate-900/40 cursor-pointer"
          />
        </div>
      )}

      {/* Desktop Collapsible Left Pane */}
      {!leftPaneCollapsed && (
        <div className="hidden h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
          <div className="flex items-center justify-end border-b border-slate-200 p-2">
            <button
              type="button"
              onClick={() => setLeftPaneCollapsed(true)}
              className="rounded p-1 text-slate-500 hover:bg-slate-100 cursor-pointer"
              aria-label="サイドバーを畳む"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          </div>

          {/* Upper Section: Project List */}
          <div className="flex flex-1 flex-col min-h-0 border-b border-slate-200">
            <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
              <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">プロジェクト</h2>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {loadingProjects ? (
                <div className="p-3 text-xs text-slate-500">読み込み中...</div>
              ) : validProjects.length === 0 ? (
                <div className="p-3 text-xs text-slate-500">プロジェクトがありません</div>
              ) : (
                validProjects.map((item) => {
                  const isSelected = item.project.project_id === selectedProjectId;
                  return (
                    <button
                      key={item.project.project_id}
                      type="button"
                      onClick={() => setSelectedProjectId(item.project.project_id)}
                      className={`w-full rounded px-3 py-2 text-left text-xs transition-colors cursor-pointer ${
                        isSelected
                          ? "bg-slate-900 font-medium text-white"
                          : "text-slate-700 hover:bg-slate-100"
                      }`}
                    >
                      <span className="truncate">{item.project.display_name}</span>
                      {item.project.domain && (
                        <div className={`mt-0.5 text-[10px] ${isSelected ? "text-slate-300" : "text-slate-400"}`}>
                          {item.project.domain} • {item.project.status}
                        </div>
                      )}
                    </button>
                  );
                })
              )}
            </div>
          </div>

          {/* Lower Section: Session List */}
          <div className="flex flex-1 flex-col min-h-0">
            <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
              <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">セッション</h2>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={handleOpenUserDefaults}
                  className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  title="ユーザー既定の利用可能ツール設定"
                >
                  既定設定
                </button>
                {selectedProjectItem && (
                  <button
                    type="button"
                    onClick={() => setIsNewSessionModalOpen(true)}
                    className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 cursor-pointer"
                    title="新規セッション作成"
                  >
                    + 新規
                  </button>
                )}
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {loadingSessions ? (
                <div className="p-3 text-xs text-slate-500">セッション読み込み中...</div>
              ) : sessions.length === 0 ? (
                <div className="p-3 text-xs text-slate-500">
                  セッションがありません。「+ 新規」から作成してください。
                </div>
              ) : (
                sessions.map((sess) => {
                  const isSelected = sess.session_id === selectedSessionId;
                  const dateStr = sess.created_at ? formatYmdWithDow(sess.created_at.slice(0, 10)) : "";
                  return (
                    <div
                      key={sess.session_id}
                      data-testid="memory-row"
                      data-selected={isSelected}
                      role="button"
                      tabIndex={0}
                      onClick={() => selectSession(sess.session_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          selectSession(sess.session_id);
                        }
                      }}
                      className={`group flex cursor-pointer items-center justify-between rounded px-3 py-2 text-xs transition-colors ${
                        isSelected
                          ? "bg-slate-200 border-l-4 border-slate-800 font-medium text-slate-900"
                          : "text-slate-700 hover:bg-slate-50"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium">{sess.title}</div>
                        <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
                          <span className="uppercase font-semibold text-slate-600">
                            {sess.backend}
                          </span>
                          {dateStr && (
                            <>
                              <span>•</span>
                              <span>{dateStr}</span>
                            </>
                          )}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => handleDeleteSession(sess.session_id, e)}
                        className="ml-2 hidden rounded p-1 text-slate-400 hover:bg-slate-300 hover:text-slate-700 group-hover:block cursor-pointer"
                        title="削除"
                      >
                        ✕
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* Pane 3: Conversation */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-slate-50">
        {error && (
          <div className="bg-red-50 p-3 text-xs text-red-700 border-b border-red-200 flex items-center justify-between">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-red-500 hover:text-red-800"
            >
              ✕
            </button>
          </div>
        )}

        {!selectedSession ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-xs text-slate-400">
            <p>セッションを選択するか、新規セッションを作成してください</p>
            {leftPaneCollapsed && (
              <button
                type="button"
                onClick={() => setLeftPaneCollapsed(false)}
                className="hidden items-center gap-1 rounded border border-slate-300 bg-slate-900 text-white px-3 py-1.5 text-xs hover:bg-slate-800 cursor-pointer lg:inline-flex"
                aria-label="サイドバーを展開"
              >
                <ChevronRight className="h-3.5 w-3.5" />
                プロジェクト / セッションを選択
              </button>
            )}
            <button
              type="button"
              onClick={() => setMobileDrawerOpen(true)}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
            >
              プロジェクト / セッションを選択
            </button>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
              <div className="min-w-0 flex-1 mr-2">
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    ref={drawerTriggerBtnRef}
                    type="button"
                    onClick={() => setMobileDrawerOpen(true)}
                    className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden shrink-0"
                    aria-label="プロジェクト / セッションを選択"
                  >
                    プロジェクト / セッション
                  </button>
                  {leftPaneCollapsed && (
                    <button
                      type="button"
                      onClick={() => setLeftPaneCollapsed(false)}
                      className="hidden h-8 w-8 items-center justify-center rounded border border-slate-300 bg-slate-900 text-white hover:bg-slate-800 cursor-pointer lg:inline-flex shrink-0"
                      aria-label="サイドバーを展開"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  )}
                  <h1 className="text-sm font-semibold text-slate-800 truncate">{selectedSession.title}</h1>
                  {sessionDetail?.has_custom_tools ? (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                      会話固有ツール設定
                    </span>
                  ) : (
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                      既定ツール適用
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium uppercase text-slate-700">
                    {selectedSession.backend}
                  </span>
                  <span>{selectedSession.repo_path}</span>
                  {gitStatus && (
                    <div className="flex items-center gap-1.5 border-l border-slate-200 pl-2">
                      <span className="font-mono font-medium text-slate-700">
                        {gitStatus.branch || "detached"}
                      </span>
                      <span className="font-mono text-slate-600" title="ahead / behind">
                        ↑{gitStatus.ahead} ↓{gitStatus.behind}
                      </span>
                      <span className="font-mono text-emerald-600 font-medium">
                        +{gitStatus.insertions}
                      </span>
                      <span className="font-mono text-rose-600 font-medium">
                        -{gitStatus.deletions}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    if (sessionDetail && sessionDetail.session.session_id === selectedSessionId) {
                      setSessionSelectedTools(sessionDetail.effective_tool_ids);
                      setSessionTitleDraft(sessionDetail.session.title ?? "");
                      setIsSessionSettingsOpen(true);
                    }
                  }}
                  className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  会話設定 ⚙
                </button>
                {currentRun && currentRun.status === "running" && (
                  <button
                    type="button"
                    onClick={handleCancelRun}
                    className="rounded bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-700 cursor-pointer"
                  >
                    キャンセル
                  </button>
                )}
              </div>
            </div>

            {/* Dirty tree warning banner if run started with uncommitted changes */}
            {currentRun?.dirty_tree_at_start && (
              <details className="bg-amber-50 text-xs text-amber-800 border-b border-amber-200">
                <summary className="cursor-pointer px-4 py-2 font-semibold hover:bg-amber-100/60 flex items-center justify-between">
                  <span>⚠️ 開始時に未コミットの変更があります</span>
                  <span className="text-[10px] text-amber-700 font-normal">クリックで展開/折りたたみ</span>
                </summary>
                <div className="px-4 pb-2">
                  <pre className="mt-1 max-h-32 overflow-y-auto text-[10px] font-mono bg-amber-100/50 p-1.5 rounded">
                    {currentRun.dirty_tree_at_start}
                  </pre>
                </div>
              </details>
            )}

            {/* Message Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 min-w-0">
              {loadingMessages ? (
                <div className="text-center text-xs text-slate-500 py-8">
                  会話履歴読み込み中...
                </div>
              ) : messages.length === 0 && !isStreaming ? (
                <div className="text-center text-xs text-slate-400 py-8">
                  ユーザーメッセージを入力してコーディングセッションを開始してください
                </div>
              ) : (
                messages.map((msg) => (
                  <div key={msg.message_id} className="space-y-1 min-w-0">
                    {msg.role === "user" && (
                      <>
                        <div className="flex flex-col items-end min-w-0">
                          {(() => {
                            const uRunId = getRunIdForUserMessage(msg);
                            const uRun = uRunId ? runById.get(uRunId) ?? null : null;
                            if (uRun?.slash_invocation) {
                              return (
                                <div className="mb-1 inline-flex items-center gap-1 rounded bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800">
                                  <span>/{uRun.slash_invocation.name}</span>
                                </div>
                              );
                            }
                            return null;
                          })()}
                          <div className="max-w-2xl min-w-0 overflow-hidden rounded-2xl bg-slate-900 px-4 py-2.5 text-xs text-white [overflow-wrap:anywhere]">
                            <p className="whitespace-pre-wrap wrap-anywhere break-words [overflow-wrap:anywhere] [word-break:break-word]">
                              {msg.content}
                            </p>
                          </div>
                        </div>
                        {sessionDetail?.ask_user_answer_history
                          ?.filter((round) => round.user_message_id === msg.message_id)
                          .map((round) => (
                            <AnsweredRequirementCard
                              key={`${round.hitl_run_id}-${round.tool_call_id}`}
                              round={round}
                            />
                          ))}
                        {(() => {
                          const userRunId = getRunIdForUserMessage(msg);
                          const unassociatedToolCalls = userRunId
                            ? unassociatedToolCallsByRunId.get(userRunId) || []
                            : [];
                          if (unassociatedToolCalls.length === 0) return null;
                          return (
                            <div className="flex justify-start my-1.5 min-w-0">
                              <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-amber-200 bg-amber-50/50 px-3 py-2">
                                <div className="text-[10px] font-bold uppercase tracking-wider text-amber-800">
                                  中断したオーケストレーター処理 ({unassociatedToolCalls.length}件)
                                </div>
                                {unassociatedToolCalls.map((tc) => (
                                  <details
                                    key={tc.call_id}
                                    className="rounded border border-amber-200 bg-white text-xs overflow-hidden group"
                                  >
                                    <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-amber-50/80 hover:bg-amber-100/80">
                                      <span className="flex items-center gap-1.5 min-w-0">
                                        <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                                        <span
                                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                            tc.status === "succeeded"
                                              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                              : tc.status === "failed"
                                              ? "bg-rose-50 text-rose-700 border-rose-200"
                                              : "bg-amber-100 text-amber-800 border-amber-300"
                                          }`}
                                        >
                                          {tc.status === "succeeded"
                                            ? "成功"
                                            : tc.status === "failed"
                                            ? "失敗"
                                            : "中断"}
                                        </span>
                                      </span>
                                      <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                                    </summary>
                                    <div className="border-t border-amber-200 p-3 space-y-2 bg-white">
                                      <div>
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
                                        <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                          {(() => {
                                            try {
                                              return JSON.stringify(tc.args, null, 2);
                                            } catch {
                                              return String(tc.args);
                                            }
                                          })()}
                                        </pre>
                                      </div>
                                      <div>
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                                        <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                          {tc.result || "-"}
                                        </pre>
                                      </div>
                                      {tc.error && (
                                        <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
                                          {tc.error}
                                        </div>
                                      )}
                                    </div>
                                  </details>
                                ))}
                              </div>
                            </div>
                          );
                        })()}
                      </>
                    )}

                    {msg.role === "orchestrator" && (
                      <>
                        {(() => {
                          const toolCalls = toolCallsByMessageId.get(msg.message_id) || [];
                          if (toolCalls.length === 0) return null;
                          return (
                            <div className="flex justify-start my-1.5 min-w-0">
                              <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                  ツール呼び出し {toolCalls.length}件
                                </div>
                                {toolCalls.map((tc) => (
                                  <details
                                    key={tc.call_id}
                                    className="rounded border border-slate-200 bg-white text-xs overflow-hidden group"
                                  >
                                    <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 hover:bg-slate-100">
                                      <span className="flex items-center gap-1.5 min-w-0">
                                        <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                                        <span
                                          className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                            tc.status === "succeeded"
                                              ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                              : tc.status === "failed"
                                              ? "bg-rose-50 text-rose-700 border-rose-200"
                                              : "bg-amber-50 text-amber-700 border-amber-200"
                                          }`}
                                        >
                                          {tc.status === "succeeded"
                                            ? "成功"
                                            : tc.status === "failed"
                                            ? "失敗"
                                            : "中断"}
                                        </span>
                                      </span>
                                      <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                                    </summary>
                                    <div className="border-t border-slate-200 p-3 space-y-2 bg-white">
                                      <div>
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
                                        <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                          {(() => {
                                            try {
                                              return JSON.stringify(tc.args, null, 2);
                                            } catch {
                                              return String(tc.args);
                                            }
                                          })()}
                                        </pre>
                                      </div>
                                      <div>
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                                        <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                          {tc.result || "-"}
                                        </pre>
                                      </div>
                                      {tc.error && (
                                        <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
                                          {tc.error}
                                        </div>
                                      )}
                                    </div>
                                  </details>
                                ))}
                              </div>
                            </div>
                          );
                        })()}
                        <div className="flex min-w-0 justify-start">
                          <div className="max-w-2xl min-w-0 overflow-hidden rounded-2xl bg-white border border-slate-200 p-4 text-xs text-slate-800 shadow-sm [overflow-wrap:anywhere]">
                            <div className="mb-1 text-[10px] font-semibold text-slate-400 uppercase">
                              AI Orchestrator
                            </div>
                            <MarkdownPreview content={msg.content} />
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                          <button
                            type="button"
                            onClick={() => handleCopyMessage(msg.content, msg.message_id)}
                            className="inline-flex items-center gap-1 cursor-pointer rounded px-1.5 py-0.5 hover:bg-slate-100 hover:text-slate-600 transition"
                            aria-label="メッセージをコピー"
                            data-testid={`copy-message-${msg.message_id}`}
                          >
                            {copiedMessageId === msg.message_id ? (
                              <>
                                <svg
                                  className="h-3.5 w-3.5 text-emerald-600"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                  aria-hidden="true"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M5 13l4 4L19 7"
                                  />
                                </svg>
                                <span className="text-emerald-700">コピーしました</span>
                              </>
                            ) : (
                              <svg
                                className="h-3.5 w-3.5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                aria-hidden="true"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2"
                                />
                              </svg>
                            )}
                          </button>
                          <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                        </div>
                      </>
                    )}

                    {msg.role === "cli_request" && (
                      <>
                        <div className="flex min-w-0 justify-start">
                          <div className="w-full max-w-2xl min-w-0">
                            <details
                              className="rounded-xl border border-blue-200 bg-blue-50 text-xs text-blue-950 shadow-sm overflow-hidden group min-w-0"
                              data-testid="cli-request-card"
                            >
                              <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 bg-blue-100/80 font-mono text-[11px] text-blue-950 font-semibold hover:bg-blue-100">
                                <span className="flex items-center gap-1.5">
                                  <span>🤖 CLI Workerへの指示</span>
                                </span>
                                <span className="text-blue-700 text-[10px] font-normal">クリックで展開/折りたたみ</span>
                              </summary>
                              <div className="p-4 overflow-x-auto max-h-80 border-t border-blue-200/60 min-w-0 [overflow-wrap:anywhere]">
                                <pre className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-blue-900 bg-blue-100/50 p-3 rounded-lg border border-blue-200/60 min-w-0 max-w-full [overflow-wrap:anywhere] wrap-anywhere break-words">
                                  {msg.content}
                                </pre>
                              </div>
                            </details>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                          <button
                            type="button"
                            onClick={() => handleCopyMessage(msg.content, msg.message_id)}
                            className="inline-flex items-center gap-1 cursor-pointer rounded px-1.5 py-0.5 hover:bg-slate-100 hover:text-slate-600 transition"
                            aria-label="指示内容をコピー"
                            data-testid={`copy-message-${msg.message_id}`}
                          >
                            {copiedMessageId === msg.message_id ? (
                              <>
                                <svg
                                  className="h-3.5 w-3.5 text-emerald-600"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                  aria-hidden="true"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M5 13l4 4L19 7"
                                  />
                                </svg>
                                <span className="text-emerald-700">コピーしました</span>
                              </>
                            ) : (
                              <svg
                                className="h-3.5 w-3.5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                aria-hidden="true"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2"
                                />
                              </svg>
                            )}
                          </button>
                          <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                        </div>
                      </>
                    )}

                    {msg.role === "worker" && (
                      <>
                        <div className="flex min-w-0 justify-start">
                          <div className="w-full max-w-2xl min-w-0">
                            <details className="rounded-xl border border-slate-200 bg-slate-900 text-slate-100 text-xs shadow-sm overflow-hidden group min-w-0">
                              <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 bg-slate-800 font-mono text-[11px] hover:bg-slate-700">
                                <span>CLI Worker 最終返答 ({selectedSession.backend})</span>
                                <span className="text-slate-400 text-[10px]">クリックで展開/折りたたみ</span>
                              </summary>
                              <div className="p-4 overflow-x-auto max-h-96 border-b border-slate-800 min-w-0 [overflow-wrap:anywhere]">
                                <MarkdownPreview content={msg.content} variant="dark" />
                              </div>

                              {/* Diagnostics Details */}
                              {currentRun?.diagnostics && (
                                <div
                                  className="p-3 bg-slate-950 font-mono text-[11px] space-y-1.5 border-t border-slate-800 text-slate-300"
                                  data-testid="worker-diagnostics"
                                >
                                  <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                                    🔍 実行診断情報 (Diagnostics)
                                  </div>
                                  <div className="grid grid-cols-1 gap-1 pl-1">
                                    <div>
                                      <span className="text-slate-500">作業ディレクトリ (cwd): </span>
                                      <span className="text-slate-200 select-all">{currentRun.diagnostics.cwd}</span>
                                    </div>
                                    <div>
                                      <span className="text-slate-500">要求セッションID: </span>
                                      <span className="text-slate-200 select-all">
                                        {currentRun.diagnostics.requested_session_id || "なし（新規起動）"}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-slate-500">返却セッションID: </span>
                                      <span className="text-slate-200 select-all">
                                        {currentRun.diagnostics.returned_session_id || "なし"}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-slate-500">ツール実行数: </span>
                                      <span className="text-slate-200">
                                        {currentRun.diagnostics.tool_call_count}回 (失敗: {currentRun.diagnostics.tool_failure_count}回)
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-slate-500">モデル/variant: </span>
                                      <span className="text-slate-200">
                                        {currentRun.diagnostics.model} / {currentRun.diagnostics.variant}
                                      </span>
                                    </div>
                                    {currentRun.diagnostics.auto_rejected_permission && (
                                      <div className="text-amber-400 font-semibold">
                                        ⚠️ 権限制限により選択リポジトリ外への操作が自動拒否されました
                                      </div>
                                    )}
                                    {currentRun.diagnostics.structured_error && (
                                      <div className="text-rose-400">
                                        <span className="text-rose-500">構造化エラー: </span>
                                        {currentRun.diagnostics.structured_error}
                                      </div>
                                    )}
                                  </div>
                                </div>
                              )}
                            </details>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-slate-400 justify-start">
                          <button
                            type="button"
                            onClick={() => handleCopyMessage(msg.content, msg.message_id)}
                            className="inline-flex items-center gap-1 cursor-pointer rounded px-1.5 py-0.5 hover:bg-slate-100 hover:text-slate-600 transition"
                            aria-label="メッセージをコピー"
                            data-testid={`copy-message-${msg.message_id}`}
                          >
                            {copiedMessageId === msg.message_id ? (
                              <>
                                <svg
                                  className="h-3.5 w-3.5 text-emerald-600"
                                  fill="none"
                                  viewBox="0 0 24 24"
                                  stroke="currentColor"
                                  aria-hidden="true"
                                >
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M5 13l4 4L19 7"
                                  />
                                </svg>
                                <span className="text-emerald-700">コピーしました</span>
                              </>
                            ) : (
                              <svg
                                className="h-3.5 w-3.5"
                                fill="none"
                                viewBox="0 0 24 24"
                                stroke="currentColor"
                                aria-hidden="true"
                              >
                                <path
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                  strokeWidth={2}
                                  d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 012-2h4a2 2 0 012 2"
                                />
                              </svg>
                            )}
                          </button>
                          <span aria-label="送信時刻">{formatDateTime(msg.created_at)}</span>
                        </div>
                      </>
                    )}
                  </div>
                ))
              )}

              {/* Streaming state UI */}
              {isStreaming && (
                <div className="space-y-3">
                  {streamingToolCalls.length > 0 && (
                    <div className="flex justify-start min-w-0">
                      <div className="max-w-2xl w-full min-w-0 space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                          ツール呼び出し {streamingToolCalls.length}件
                        </div>
                        {streamingToolCalls.map((tc) => (
                          <details
                            key={tc.id}
                            className="rounded border border-slate-200 bg-white text-xs overflow-hidden group"
                          >
                            <summary className="cursor-pointer list-none flex items-center justify-between gap-2 px-3 py-1.5 bg-slate-50 hover:bg-slate-100">
                              <span className="flex items-center gap-1.5 min-w-0">
                                <span className="font-semibold truncate text-slate-800">{tc.tool_name}</span>
                                <span
                                  className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${
                                    tc.status === "succeeded"
                                      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                      : tc.status === "failed"
                                      ? "bg-rose-50 text-rose-700 border-rose-200"
                                      : tc.status === "running"
                                      ? "bg-amber-50 text-amber-700 border-amber-200"
                                      : "bg-blue-50 text-blue-700 border-blue-200"
                                  }`}
                                >
                                  {tc.status === "succeeded"
                                    ? "成功"
                                    : tc.status === "failed"
                                    ? "失敗"
                                    : tc.status === "running"
                                    ? "実行中…"
                                    : "準備中…"}
                                </span>
                              </span>
                              <span className="text-[10px] text-slate-400 group-open:rotate-180 transition-transform shrink-0">▼</span>
                            </summary>
                            <div className="border-t border-slate-200 p-3 space-y-2 bg-white">
                              {tc.status === "preparing" ? (
                                <div className="flex items-center gap-2 text-[11px] text-blue-700">
                                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-blue-200 border-t-blue-600" />
                                  ツール呼び出しを準備中…
                                </div>
                              ) : (
                                <>
                                  <div>
                                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">引数</div>
                                    <pre className="max-h-40 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                      {(() => {
                                        try {
                                          return JSON.stringify(tc.args, null, 2);
                                        } catch {
                                          return String(tc.args);
                                        }
                                      })()}
                                    </pre>
                                  </div>
                                  {tc.status !== "running" && (
                                    <div>
                                      <div className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1">結果</div>
                                      <pre className="max-h-64 overflow-auto rounded bg-slate-50 border border-slate-200 p-2 text-[11px] font-mono whitespace-pre-wrap break-all">
                                        {tc.result || "-"}
                                      </pre>
                                    </div>
                                  )}
                                </>
                              )}
                              {tc.status === "running" && (
                                <div className="flex items-center gap-2 text-[11px] text-amber-700">
                                  <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-amber-300 border-t-amber-600" />
                                  実行中…
                                </div>
                              )}
                              {tc.error && (
                                <div className="text-[11px] text-rose-700 bg-rose-50 border border-rose-200 rounded px-2 py-1 break-all">
                                  {tc.error}
                                </div>
                              )}
                            </div>
                          </details>
                        ))}
                      </div>
                    </div>
                  )}

                  {activePhaseText && (
                    <div className="flex justify-start">
                      <div className="rounded-xl bg-white border border-slate-200 p-3 text-xs text-slate-700 shadow-sm flex items-center gap-2">
                        <span className="inline-block h-2 w-2 animate-ping rounded-full bg-slate-600" />
                        <span>AI Orchestrator: {activePhaseText}</span>
                      </div>
                    </div>
                  )}

                  {workerState.status === "running" && (
                    <div className="flex justify-start">
                      <div className="rounded-xl bg-slate-800 p-3 text-xs text-slate-200 font-mono flex items-center gap-2">
                        <span className="inline-block h-2 w-2 animate-ping rounded-full bg-emerald-400" />
                        CLIワーカー {workerState.attempt ? `(${workerState.attempt}回目)` : ""} ({workerState.backend}) 実行中...
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Run status badge when run finishes with error or cancellation */}
              {currentRun && currentRun.status !== "running" && currentRun.status !== "completed" && (
                <div className="p-2 text-center text-xs">
                  <span
                    className={`inline-block rounded px-2 py-1 font-medium ${
                      currentRun.status === "failed"
                        ? "bg-red-100 text-red-800"
                        : currentRun.status === "cancelled"
                        ? "bg-slate-200 text-slate-700"
                        : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    ステータス: {currentRun.status}
                    {currentRun.error_message && ` (${currentRun.error_message})`}
                  </span>
                </div>
              )}

              {/* In-Conversation Active Question Card (message flow bottom) */}
              {activeWaitingRun && activeWaitingRun.questions.length > 0 && (
                <WaitingRunQuestionCard
                  key={activeWaitingRun.hitlRunId}
                  hitlRunId={activeWaitingRun.hitlRunId}
                  questions={activeWaitingRun.questions}
                  onSubmit={(answers) => handleSubmitWaitingAnswers(activeWaitingRun, answers)}
                  onCancel={() => handleCancelWaitingRun(activeWaitingRun)}
                />
              )}
              {activeWaitingRun && activeWaitingRun.questions.length === 0 && (
                <WaitingRunStatusPanel
                  key={`${activeWaitingRun.hitlRunId}-status`}
                  hitlRunId={activeWaitingRun.hitlRunId}
                  status={activeWaitingRun.hitlStatus}
                  errorMessage={activeWaitingRun.hitlError}
                  onCancel={() => handleCancelWaitingRun(activeWaitingRun)}
                />
              )}

              <div ref={messageEndRef} />
            </div>

            {/* Input Form */}
            <div className="border-t border-slate-200 bg-white p-3 relative">
              {/* Candidate Palette Popover */}
              {showSlashPalette && (
                <div className="absolute bottom-full left-3 mb-1 z-20 w-80 max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-lg text-xs">
                  {!hasSkillsTool ? (
                    <div className="p-2 text-slate-500 text-center">
                      skills ツールが無効なためスキルコマンドは利用できません
                    </div>
                  ) : filteredCandidates.length === 0 ? (
                    <div className="p-2 text-slate-500 text-center">
                      一致するスキルが見つかりません
                    </div>
                  ) : (
                    filteredCandidates.map((cand, idx) => {
                      const isSelected = idx === slashPaletteIndex;
                      return (
                        <button
                          key={cand.name}
                          type="button"
                          onClick={() => handleSelectCandidate(cand)}
                          className={`w-full text-left px-2.5 py-1.5 rounded flex flex-col gap-0.5 cursor-pointer ${
                            isSelected ? "bg-slate-100 text-slate-900 font-medium" : "text-slate-700 hover:bg-slate-50"
                          }`}
                        >
                          <div className="font-semibold text-slate-800">/{cand.name}</div>
                          {cand.description && (
                            <div className="text-[10px] text-slate-500 truncate">{cand.description}</div>
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
              )}

              {/* Selected Skill Chip */}
              {slashInvocation && (
                <div className="mb-2 flex items-center gap-1.5">
                  <span className="inline-flex items-center gap-1 rounded bg-blue-100 px-2.5 py-1 text-xs font-semibold text-blue-800 border border-blue-200">
                    <span>/{slashInvocation.name}</span>
                    <button
                      type="button"
                      onClick={() => setSlashInvocation(null)}
                      className="ml-1 rounded hover:bg-blue-200 p-0.5 text-blue-600 hover:text-blue-900 cursor-pointer"
                      title="スキル選択を解除"
                    >
                      ✕
                    </button>
                  </span>
                </div>
              )}

              <form onSubmit={handleSendMessage} className="flex gap-2">
                <textarea
                  rows={2}
                  value={inputContent}
                  onChange={(e) => setInputContent(e.target.value)}
                  onKeyDown={handleInputKeyDown}
                  placeholder={codingPlaceholder}
                  disabled={isStreaming || currentRun?.status === "running"}
                  className="flex-1 resize-none rounded-lg border border-slate-300 p-2 text-xs focus:border-slate-800 focus:outline-none disabled:bg-slate-100"
                />
                <button
                  type="submit"
                  disabled={
                    !inputContent.trim() || isStreaming || currentRun?.status === "running"
                  }
                  className="rounded bg-slate-900 px-4 text-xs font-medium text-white hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-300"
                >
                  送信
                </button>
              </form>
            </div>
          </>
        )}
      </div>

      {/* Conversation Settings Modal */}
      {isSessionSettingsOpen && sessionDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] flex flex-col">
            <h3 className="text-base font-semibold text-slate-900">会話の利用可能ツール設定</h3>
            <p className="mt-1 text-xs text-slate-500">
              オーケストレーターがこの会話で呼び出せるツールを選択してください。
              未選択のツールは呼び出せなくなります。
            </p>

            <div className="mt-4">
              <label
                htmlFor="coding-session-title"
                className="block text-xs font-medium text-slate-700"
              >
                セッションタイトル
              </label>
              <input
                id="coding-session-title"
                type="text"
                value={sessionTitleDraft}
                onChange={(e) => setSessionTitleDraft(e.target.value)}
                placeholder="セッションタイトルを入力"
                disabled={savingSessionTools}
                className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-slate-800 focus:outline-none disabled:bg-slate-100"
              />
            </div>

            <div className="mt-3 flex items-center justify-between border-b border-slate-200 pb-2 text-xs">
              <span className="text-slate-600 font-medium">
                選択中: {sessionSelectedTools.length} / {sessionDetail.available_tools.length} 個
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() =>
                    setSessionSelectedTools(sessionDetail.available_tools.map((t) => t.tool_id))
                  }
                  className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                >
                  全選択
                </button>
                <button
                  type="button"
                  onClick={() => setSessionSelectedTools([])}
                  className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                >
                  全解除
                </button>
              </div>
            </div>

            <div className="mt-3 flex-1 overflow-y-auto space-y-1.5 pr-1">
              {sessionDetail.available_tools.map((tool) => {
                const isChecked = sessionSelectedTools.includes(tool.tool_id);
                return (
                  <label
                    key={tool.tool_id}
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                      isChecked
                        ? "border-slate-800 bg-slate-50 text-slate-900"
                        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSessionSelectedTools((prev) => [...prev, tool.tool_id]);
                        } else {
                          setSessionSelectedTools((prev) =>
                            prev.filter((tid) => tid !== tool.tool_id)
                          );
                        }
                      }}
                      className="rounded border-slate-300 text-slate-900 focus:ring-slate-800 cursor-pointer"
                    />
                    <span className="font-semibold text-slate-800">
                      {tool.name} <span className="text-[10px] text-slate-400 font-mono">({tool.tool_id})</span>
                    </span>
                  </label>
                );
              })}
            </div>

            <div className="mt-6 flex items-center justify-between border-t border-slate-200 pt-4">
              <button
                type="button"
                disabled={savingSessionTools || !sessionDetail.has_custom_tools}
                onClick={handleResetSessionTools}
                className="rounded px-3 py-1.5 text-xs font-medium text-rose-700 hover:bg-rose-50 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                title="既定ツール設定へリセット"
              >
                既定値に戻す
              </button>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setIsSessionSettingsOpen(false)}
                  className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
                >
                  キャンセル
                </button>
                <button
                  type="button"
                  disabled={savingSessionTools}
                  onClick={handleSaveSessionTools}
                  className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {savingSessionTools ? "保存中..." : "保存"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* User Default Tools Modal */}
      {isUserDefaultsOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl max-h-[90vh] flex flex-col">
            <h3 className="text-base font-semibold text-slate-900">ユーザー既定の利用可能ツール設定</h3>
            <p className="mt-1 text-xs text-slate-500">
              新規会話作成時にデフォルトで許可されるツールセットを設定します。
            </p>

            {loadingUserDefaults ? (
              <div className="py-8 text-center text-xs text-slate-500">読み込み中...</div>
            ) : userDefaults ? (
              <>
                <div className="mt-3 flex items-center justify-between border-b border-slate-200 pb-2 text-xs">
                  <span className="text-slate-600 font-medium">
                    選択中: {userDefaultsSelectedTools.length} / {userDefaults.available_tools.length} 個
                  </span>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setUserDefaultsSelectedTools(userDefaults.available_tools.map((t) => t.tool_id))
                      }
                      className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                    >
                      全選択
                    </button>
                    <button
                      type="button"
                      onClick={() => setUserDefaultsSelectedTools([])}
                      className="text-slate-600 hover:text-slate-900 text-[11px] underline"
                    >
                      全解除
                    </button>
                  </div>
                </div>

                <div className="mt-3 flex-1 overflow-y-auto space-y-1.5 pr-1">
                  {userDefaults.available_tools.map((tool) => {
                    const isChecked = userDefaultsSelectedTools.includes(tool.tool_id);
                    return (
                      <label
                        key={tool.tool_id}
                        className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs cursor-pointer transition-colors ${
                          isChecked
                            ? "border-slate-800 bg-slate-50 text-slate-900"
                            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setUserDefaultsSelectedTools((prev) => [...prev, tool.tool_id]);
                            } else {
                              setUserDefaultsSelectedTools((prev) =>
                                prev.filter((tid) => tid !== tool.tool_id)
                              );
                            }
                          }}
                          className="rounded border-slate-300 text-slate-900 focus:ring-slate-800 cursor-pointer"
                        />
                        <span className="font-semibold text-slate-800">
                          {tool.name} <span className="text-[10px] text-slate-400 font-mono">({tool.tool_id})</span>
                        </span>
                      </label>
                    );
                  })}
                </div>

                <div className="mt-6 flex justify-end gap-2 border-t border-slate-200 pt-4">
                  <button
                    type="button"
                    onClick={() => setIsUserDefaultsOpen(false)}
                    className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
                  >
                    キャンセル
                  </button>
                  <button
                    type="button"
                    disabled={savingUserDefaults}
                    onClick={handleSaveUserDefaults}
                    className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {savingUserDefaults ? "保存中..." : "既定値として保存"}
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* New Session Modal */}
      {isNewSessionModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <h3 className="text-base font-semibold text-slate-900">新規コーディングセッション作成</h3>
            <p className="mt-1 text-xs text-slate-500">
              プロジェクト: {selectedProjectItem?.project.display_name}
            </p>

            <div className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-700">
                  セッションタイトル
                </label>
                <input
                  type="text"
                  value={newSessionTitle}
                  onChange={(e) => setNewSessionTitle(e.target.value)}
                  placeholder="自動生成 (空欄可) / 例: リファクタリング作業"
                  className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-slate-800 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700">
                  CLI バックエンド選択
                </label>
                <div className="mt-2 grid grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => {
                      backendManuallySelected.current = true;
                      setNewSessionBackend("codex");
                    }}
                    className={`rounded-lg border p-3 text-left text-xs transition-colors ${
                      newSessionBackend === "codex"
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">Codex CLI</div>
                    <div className="mt-0.5 text-[10px] opacity-80">OpenAI Codex アダプタ</div>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      backendManuallySelected.current = true;
                      setNewSessionBackend("opencode");
                    }}
                    className={`rounded-lg border p-3 text-left text-xs transition-colors ${
                      newSessionBackend === "opencode"
                        ? "border-slate-900 bg-slate-900 text-white"
                        : "border-slate-200 bg-white text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    <div className="font-semibold">OpenCode CLI</div>
                    <div className="mt-0.5 text-[10px] opacity-80">OpenCode CLI アダプタ</div>
                  </button>
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setIsNewSessionModalOpen(false)}
                className="rounded px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 cursor-pointer"
              >
                キャンセル
              </button>
              <button
                type="button"
                disabled={creatingSession}
                onClick={handleCreateSession}
                className="rounded bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creatingSession ? "作成中..." : "作成"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
