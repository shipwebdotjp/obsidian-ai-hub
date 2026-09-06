import { useEffect, useRef, useState, type MutableRefObject } from "react";
import type { SetURLSearchParams } from "react-router-dom";
import {
  createAgentSession,
  deleteAgentSession,
  getAgentSessionDetail,
  getHitlRun,
  cancelHitlRun,
  submitHitlAnswer,
  listAgentSessions,
  searchAgentMessages,
  updateAgentSession,
} from "../../api/client";
import type {
  AgentMessage,
  AgentMessageSearchResult,
  AgentRun,
  AgentSession,
  AskUserAnswerRound,
} from "../../api/types";
import {
  toQuestionItems,
  waitForHitlSettled,
  type ActiveWaitingRun,
} from "../../components/InConversationQuestionCard";
import {
  clearLastViewedSessionId,
  writeLastViewedSessionId,
} from "./lastViewedSession";

interface UseAgentSessionsOptions {
  selectedAgentId: string | null;
  setSelectedAgentId: React.Dispatch<React.SetStateAction<string | null>>;
  selectedSessionIdRef: MutableRefObject<string | null>;
  onActionError: (message: string | null) => void;
  onChatError: (message: string | null) => void;
  setSearchParams: SetURLSearchParams;
  pendingSessionIdRef: MutableRefObject<string | null>;
  pendingSourceRef: MutableRefObject<"deeplink" | "storage" | null>;
  storageRestoreIdRef: MutableRefObject<string | null>;
  closeMobileDrawer: () => void;
}

/** 会話セッション一覧・選択・詳細・検索・HITL・タイトル変更を管理する。 */
export function useAgentSessions({
  selectedAgentId,
  setSelectedAgentId,
  selectedSessionIdRef,
  onActionError,
  onChatError,
  setSearchParams,
  pendingSessionIdRef,
  pendingSourceRef,
  storageRestoreIdRef,
  closeMobileDrawer,
}: UseAgentSessionsOptions) {
  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [answerHistory, setAnswerHistory] = useState<AskUserAnswerRound[]>([]);
  const [activeWaitingRun, setActiveWaitingRun] = useState<ActiveWaitingRun | null>(null);
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);
  const [sessionSearchQuery, setSessionSearchQuery] = useState("");
  const [sessionSearchResults, setSessionSearchResults] = useState<AgentMessageSearchResult[]>([]);
  const [isSessionSearchLoading, setIsSessionSearchLoading] = useState(false);
  const [sessionSearchError, setSessionSearchError] = useState<string | null>(null);

  // Session title edit & action menu
  const [sessionToDelete, setSessionToDelete] = useState<AgentSession | null>(null);
  const [activeSessionMenuId, setActiveSessionMenuId] = useState<string | null>(null);
  const [sessionToEditTitle, setSessionToEditTitle] = useState<AgentSession | null>(null);
  const [editTitleText, setEditTitleText] = useState("");
  const [editTitleError, setEditTitleError] = useState<string | null>(null);

  const messageElementRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingSearchTargetRef = useRef<{ sessionId: string; messageId: string } | null>(null);

  const loadSessions = async (agentId: string) => {
    onActionError(null);
    try {
      const res = await listAgentSessions(agentId);
      setSessions(res.sessions);
      const target = pendingSessionIdRef.current;
      const targetSource = pendingSourceRef.current;
      if (target && res.sessions.some((s) => s.session_id === target)) {
        setSelectedSessionId(target);
      } else if (target) {
        // Target session does not belong to this agent: drop it and fall back.
        pendingSessionIdRef.current = null;
        pendingSourceRef.current = null;
        if (targetSource === "storage") {
          // Stored session is gone from this agent: erase it. There is no URL
          // param to clean on an ID-less entry.
          clearLastViewedSessionId();
          storageRestoreIdRef.current = null;
        } else {
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.delete("session_id");
              return next;
            },
            { replace: true },
          );
        }
        if (res.sessions.length > 0) {
          setSelectedSessionId(res.sessions[0].session_id);
        } else {
          setSelectedSessionId(null);
          setMessages([]);
        }
      } else if (res.sessions.length > 0) {
        setSelectedSessionId((prev) => {
          if (prev && res.sessions.some((s) => s.session_id === prev)) {
            return prev;
          }
          return res.sessions[0].session_id;
        });
      } else {
        setSelectedSessionId(null);
        setMessages([]);
      }
      pendingSessionIdRef.current = null;
      pendingSourceRef.current = null;
    } catch (e: unknown) {
      onActionError(e instanceof Error ? e.message : "会話履歴の読み込みに失敗しました。");
    }
  };

  /** エージェント切替時のセッション追従（購読破棄・ストリーミング初期化は呼び出し側）。 */
  const handleAgentChanged = async (agentId: string | null) => {
    if (!agentId) {
      setSessions([]);
      setSelectedSessionId(null);
      setMessages([]);
      setLoadedSessionId(null);
      return;
    }
    await loadSessions(agentId);
  };

  const loadSessionDetail = async (sessionId: string) => {
    onActionError(null);
    try {
      const detail = await getAgentSessionDetail(sessionId);
      // The selection is confirmed: this session is actually displayed, so
      // record it as the last-viewed session. Skip stale responses that
      // arrived after the user moved to another session.
      if (selectedSessionIdRef.current === sessionId) {
        writeLastViewedSessionId(sessionId);
      }
      if (storageRestoreIdRef.current === sessionId) {
        storageRestoreIdRef.current = null;
      }
      setMessages(detail.messages);
      const sessionRuns = detail.runs || [];
      setRuns(sessionRuns);
      setAnswerHistory(detail.ask_user_answer_history || []);
      setLoadedSessionId(sessionId);
      onChatError(null);

      // Check if latest run is waiting_user and fetch its active question set
      const waitingRun = [...sessionRuns].reverse().find((r) => r.status === "waiting_user");
      if (waitingRun && waitingRun.hitl_run_id) {
        try {
          const hitlDetail = await getHitlRun(waitingRun.hitl_run_id);
          const activeQuestions = toQuestionItems(hitlDetail.questions || []);
          setActiveWaitingRun({
            hitlRunId: waitingRun.hitl_run_id,
            questions: activeQuestions,
            hitlStatus: (hitlDetail.status as string | null) ?? null,
            hitlError: (hitlDetail.error_message as string | null) ?? null,
          });
        } catch (e: unknown) {
          console.error("Failed to load HITL question set", e);
          setActiveWaitingRun(null);
          onChatError(e instanceof Error ? e.message : "確認質問の読み込みに失敗しました。");
        }
      } else {
        setActiveWaitingRun(null);
      }
    } catch (e: unknown) {
      // A storage-restored session that no longer loads is unrestorable:
      // erase the stored value and silently fall back to the first session,
      // mirroring the invalid deep-link fallback. Normal selections keep the
      // existing error display.
      if (storageRestoreIdRef.current === sessionId) {
        storageRestoreIdRef.current = null;
        clearLastViewedSessionId();
        if (sessions.length > 0) {
          setSelectedSessionId(sessions[0].session_id);
        } else {
          setSelectedSessionId(null);
          setMessages([]);
        }
        return;
      }
      const message =
        e instanceof Error ? e.message : "セッション詳細の読み込みに失敗しました。";
      onChatError(message);
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
      // restore then resubscribes the same run ID from the existing cursor.
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
    } catch (e: unknown) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      onChatError(e instanceof Error ? e.message : "回答の送信に失敗しました");
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
    } catch (e: unknown) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      onChatError(e instanceof Error ? e.message : "質問の取消に失敗しました");
    }
  };

  const resetForEmptySession = () => {
    setMessages([]);
    setLoadedSessionId(null);
  };

  // Session Actions
  const handleCreateSession = async () => {
    if (!selectedAgentId) return;
    onActionError(null);
    try {
      const res = await createAgentSession(selectedAgentId);
      setSessions((prev) => [res.session, ...prev]);
      setSelectedSessionId(res.session.session_id);
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("session_id", res.session.session_id);
          return next;
        },
        { replace: true },
      );
    } catch (e: unknown) {
      onActionError("セッション作成に失敗しました: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const handleSelectSession = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("session_id", sessionId);
        return next;
      },
      { replace: true },
    );
  };

  const handleSelectSearchResult = (result: AgentMessageSearchResult) => {
    const isCurrentSession =
      selectedSessionId === result.session_id && loadedSessionId === result.session_id;
    if (isCurrentSession) {
      closeMobileDrawer();
      messageElementRefs.current
        .get(result.message_id)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }

    pendingSearchTargetRef.current = {
      sessionId: result.session_id,
      messageId: result.message_id,
    };
    // The session list reloads when the agent changes. Reuse the existing
    // deep-link target so that reload cannot replace this search selection.
    pendingSessionIdRef.current =
      result.agent_id === selectedAgentId ? null : result.session_id;
    // Search origin is neither a deep link nor a storage restore; keep the
    // existing invalid-target handling (URL param cleanup).
    pendingSourceRef.current = null;
    setSelectedAgentId(result.agent_id);
    setSelectedSessionId(result.session_id);
    closeMobileDrawer();
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set("session_id", result.session_id);
        return next;
      },
      { replace: true },
    );
  };

  const handleDeleteSessionConfirm = async () => {
    if (!sessionToDelete) return;
    const deletedId = sessionToDelete.session_id;
    const wasSelected = selectedSessionId === deletedId;
    onActionError(null);
    try {
      await deleteAgentSession(deletedId);
      const remaining = sessions.filter((s) => s.session_id !== deletedId);
      setSessions((prev) => prev.filter((s) => s.session_id !== deletedId));
      setSessionToDelete(null);
      if (wasSelected) {
        const nextId = remaining.length > 0 ? remaining[0].session_id : null;
        setSelectedSessionId(nextId);
        if (nextId) {
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("session_id", nextId);
              return next;
            },
            { replace: true },
          );
        } else {
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.delete("session_id");
              return next;
            },
            { replace: true },
          );
        }
      }
    } catch (e: unknown) {
      onActionError("セッション削除に失敗しました: " + (e instanceof Error ? e.message : String(e)));
      setSessionToDelete(null);
    }
  };

  const handleOpenEditTitle = (session: AgentSession) => {
    setSessionToEditTitle(session);
    setEditTitleText(session.title);
    setEditTitleError(null);
    setActiveSessionMenuId(null);
  };

  const handleSaveSessionTitle = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sessionToEditTitle) return;
    const cleanTitle = editTitleText.trim();
    if (!cleanTitle) {
      setEditTitleError("会話タイトルを入力してください。");
      return;
    }
    setEditTitleError(null);
    try {
      const res = await updateAgentSession(sessionToEditTitle.session_id, {
        title: cleanTitle,
      });
      setSessions((prev) =>
        prev.map((s) => (s.session_id === res.session.session_id ? res.session : s))
      );
      setSessionToEditTitle(null);
      if (selectedAgentId) {
        await loadSessions(selectedAgentId);
      }
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "会話タイトルの更新に失敗しました。";
      setEditTitleError(message);
    }
  };

  const handleToggleSessionPin = async (session: AgentSession, e: React.MouseEvent) => {
    e.stopPropagation();
    onActionError(null);
    try {
      await updateAgentSession(session.session_id, { pinned: !session.pinned_at });
      if (selectedAgentId) {
        const res = await listAgentSessions(selectedAgentId);
        setSessions(res.sessions);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "ピン留めの更新に失敗しました。";
      onActionError(message);
    }
  };

  useEffect(() => {
    const query = sessionSearchQuery.trim();
    if (!query) {
      setSessionSearchResults([]);
      setSessionSearchError(null);
      setIsSessionSearchLoading(false);
      return;
    }

    let cancelled = false;
    setIsSessionSearchLoading(true);
    setSessionSearchError(null);
    const timer = window.setTimeout(() => {
      void searchAgentMessages(query)
        .then((res) => {
          if (!cancelled) setSessionSearchResults(res.results);
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setSessionSearchResults([]);
            setSessionSearchError(
              error instanceof Error ? error.message : "会話履歴の検索に失敗しました。",
            );
          }
        })
        .finally(() => {
          if (!cancelled) setIsSessionSearchLoading(false);
        });
    }, 200);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [sessionSearchQuery]);

  useEffect(() => {
    const target = pendingSearchTargetRef.current;
    if (!target || loadedSessionId !== target.sessionId) return;

    const messageElement = messageElementRefs.current.get(target.messageId);
    if (!messageElement) return;
    messageElement.scrollIntoView({ behavior: "smooth", block: "center" });
    pendingSearchTargetRef.current = null;
  }, [loadedSessionId, messages]);

  return {
    sessions,
    setSessions,
    selectedSessionId,
    setSelectedSessionId,
    messages,
    setMessages,
    runs,
    setRuns,
    answerHistory,
    activeWaitingRun,
    setActiveWaitingRun,
    loadedSessionId,
    setLoadedSessionId,
    sessionSearchQuery,
    setSessionSearchQuery,
    sessionSearchResults,
    isSessionSearchLoading,
    sessionSearchError,
    sessionToDelete,
    setSessionToDelete,
    activeSessionMenuId,
    setActiveSessionMenuId,
    sessionToEditTitle,
    setSessionToEditTitle,
    editTitleText,
    setEditTitleText,
    editTitleError,
    messageElementRefs,
    loadSessions,
    loadSessionDetail,
    handleAgentChanged,
    resetForEmptySession,
    handleSubmitWaitingAnswers,
    handleCancelWaitingRun,
    handleCreateSession,
    handleSelectSession,
    handleSelectSearchResult,
    handleDeleteSessionConfirm,
    handleOpenEditTitle,
    handleSaveSessionTitle,
    handleToggleSessionPin,
  };
}
