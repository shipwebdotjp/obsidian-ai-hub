import { useRef, useState, type MutableRefObject } from "react";
import {
  getCodingDefaults,
  getCodingSessionDetail,
  getGitStatus,
  updateCodingDefaults,
  updateCodingSessionOrchestrator,
  updateCodingSessionTitle,
  updateCodingSessionTools,
  type CodingDefaults,
  type CodingMessage,
  type CodingRun,
  type CodingSession,
  type CodingSessionDetail,
  type GitStatus,
} from "../../../api/coding";
import { cancelHitlRun, getHitlRun, submitHitlAnswer } from "../../../api/client";
import {
  toQuestionItems,
  waitForHitlSettled,
  type ActiveWaitingRun,
} from "../../../components/InConversationQuestionCard";

interface UseCodingSessionDetailOptions {
  selectedSessionId: string | null;
  selectedSession: CodingSession | undefined;
  selectedSessionIdRef: MutableRefObject<string | null>;
  onError: (message: string | null) => void;
  setSessions: React.Dispatch<React.SetStateAction<CodingSession[]>>;
  refreshSlashCandidates: (sessionId: string) => Promise<void>;
}

/** 会話詳細・メッセージ・run・HITL・git 状態とツール設定モーダルを管理する。 */
export function useCodingSessionDetail({
  selectedSessionId,
  selectedSession,
  selectedSessionIdRef,
  onError,
  setSessions,
  refreshSlashCandidates,
}: UseCodingSessionDetailOptions) {
  const [sessionDetail, setSessionDetail] = useState<CodingSessionDetail | null>(null);
  const [messages, setMessages] = useState<CodingMessage[]>([]);
  const [activeRun, setActiveRun] = useState<CodingRun | null>(null);
  const [latestRun, setLatestRun] = useState<CodingRun | null>(null);
  const [activeWaitingRun, setActiveWaitingRun] = useState<ActiveWaitingRun | null>(null);
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null);
  const [loadingMessages, setLoadingMessages] = useState(false);
  // Detail (active/latest run) has been loaded for this session. The send
  // queue only flushes once this matches the selected session.
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);

  // Conversation tool settings modal state
  const [isSessionSettingsOpen, setIsSessionSettingsOpen] = useState(false);
  const [sessionSelectedTools, setSessionSelectedTools] = useState<string[]>([]);
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [orchestratorProviderDraft, setOrchestratorProviderDraft] = useState("");
  const [orchestratorModelDraft, setOrchestratorModelDraft] = useState("");
  // Remembers the model typed for each provider while the settings modal is
  // open, so switching providers back and forth does not lose a custom model.
  const orchestratorModelDraftsRef = useRef<Record<string, string>>({});
  const [savingSessionTools, setSavingSessionTools] = useState(false);

  // User default tool settings modal state
  const [isUserDefaultsOpen, setIsUserDefaultsOpen] = useState(false);
  const [userDefaults, setUserDefaults] = useState<CodingDefaults | null>(null);
  const [userDefaultsSelectedTools, setUserDefaultsSelectedTools] = useState<string[]>([]);
  const [loadingUserDefaults, setLoadingUserDefaults] = useState(false);
  const [savingUserDefaults, setSavingUserDefaults] = useState(false);

  const fetchGitStatus = async (repoPath: string, targetSessionId: string) => {
    try {
      const status = await getGitStatus(repoPath);
      if (selectedSessionIdRef.current === targetSessionId) {
        setGitStatus(status);
      }
    } catch (_) {
      if (selectedSessionIdRef.current === targetSessionId) {
        setGitStatus(null);
      }
    }
  };

  const loadSessionDetail = async (sessionId: string) => {
    // Invalidate the previous load so the send queue never flushes against
    // stale active/latest run state while this fetch is in flight.
    setLoadedSessionId(null);
    setLoadingMessages(true);
    try {
      const data = await getCodingSessionDetail(sessionId);
      if (selectedSessionIdRef.current !== sessionId) return;
      setLoadedSessionId(sessionId);
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
          if (selectedSessionIdRef.current !== sessionId) return;
          setActiveWaitingRun({
            hitlRunId: lRun.hitl_run_id,
            questions: toQuestionItems(hitlDetail.questions || []),
            hitlStatus: (hitlDetail.status as string | null) ?? null,
            hitlError: (hitlDetail.error_message as string | null) ?? null,
          });
        } catch (e) {
          console.error("Failed to load HITL run:", e);
          if (selectedSessionIdRef.current !== sessionId) return;
          setActiveWaitingRun(null);
          onError("質問の取得に失敗しました。再読み込みしてください。");
        }
      } else {
        setActiveWaitingRun(null);
      }
      if (data.session.repo_path) {
        fetchGitStatus(data.session.repo_path, sessionId);
      } else {
        if (selectedSessionIdRef.current === sessionId) {
          setGitStatus(null);
        }
      }
    } catch (e: any) {
      if (selectedSessionIdRef.current !== sessionId) return;
      setLoadedSessionId(null);
      setSessionDetail(null);
      setGitStatus(null);
      onError(e.message || "セッション詳細の取得に失敗しました");
    } finally {
      setLoadingMessages(false);
    }
  };

  const resetForEmptySession = () => {
    setLoadedSessionId(null);
    setSessionDetail(null);
    setMessages([]);
    setActiveRun(null);
    setLatestRun(null);
    setActiveWaitingRun(null);
    setGitStatus(null);
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
      onError(e.message || "回答の送信に失敗しました");
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
      onError(e.message || "質問の取消に失敗しました");
    }
  };

  const openSessionSettings = () => {
    if (sessionDetail && sessionDetail.session.session_id === selectedSessionId) {
      setSessionSelectedTools(sessionDetail.effective_tool_ids);
      setSessionTitleDraft(sessionDetail.session.title ?? "");
      const provider = sessionDetail.session.orchestrator_provider ?? "";
      const model = sessionDetail.session.orchestrator_model ?? "";
      setOrchestratorProviderDraft(provider);
      setOrchestratorModelDraft(model);
      orchestratorModelDraftsRef.current = provider ? { [provider]: model } : {};
      setIsSessionSettingsOpen(true);
    }
  };

  const handleOrchestratorProviderChange = (next: string) => {
    const previous = orchestratorProviderDraft;
    if (previous) {
      orchestratorModelDraftsRef.current[previous] = orchestratorModelDraft;
    }
    setOrchestratorProviderDraft(next);
    if (!next) {
      setOrchestratorModelDraft("");
      return;
    }
    const remembered = orchestratorModelDraftsRef.current[next];
    if (remembered !== undefined) {
      setOrchestratorModelDraft(remembered);
      return;
    }
    // The global default model only belongs to the default provider.
    setOrchestratorModelDraft(
      next === sessionDetail?.default_orchestrator_provider
        ? sessionDetail?.default_orchestrator_model ?? ""
        : "",
    );
  };

  const handleSaveSessionTools = async () => {
    if (!selectedSessionId) return;
    const opSessionId = selectedSessionId;
    const trimmedTitle = sessionTitleDraft.trim();
    if (!trimmedTitle) {
      onError("セッションタイトルを入力してください");
      return;
    }
    if (orchestratorProviderDraft.trim() && !orchestratorModelDraft.trim()) {
      onError("オーケストレーターのモデルを入力してください");
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
          onError(e.message || "セッションタイトルの保存に失敗しました");
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

      const currentProvider = sessionDetail?.session.orchestrator_provider ?? "";
      const currentModel = sessionDetail?.session.orchestrator_model ?? "";
      const desiredProvider = orchestratorProviderDraft.trim();
      const desiredModel = orchestratorModelDraft.trim();
      if (
        desiredProvider !== currentProvider ||
        (desiredProvider !== "" && desiredModel !== currentModel)
      ) {
        try {
          const orchUpdated = await updateCodingSessionOrchestrator(
            opSessionId,
            desiredProvider || null,
            desiredProvider ? desiredModel : null,
          );
          if (selectedSessionIdRef.current !== opSessionId) return;
          setSessionDetail(orchUpdated);
        } catch (e: any) {
          if (selectedSessionIdRef.current !== opSessionId) return;
          onError(e.message || "オーケストレーター設定の保存に失敗しました");
          return;
        }
      }

      setIsSessionSettingsOpen(false);
      await refreshSlashCandidates(opSessionId);
    } catch (e: any) {
      if (selectedSessionIdRef.current !== opSessionId) return;
      onError(e.message || "会話ツールの保存に失敗しました");
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
      onError(e.message || "会話ツールのリセットに失敗しました");
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
      onError(e.message || "ユーザー既定値の取得に失敗しました");
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
      onError(e.message || "ユーザー既定値の保存に失敗しました");
    } finally {
      setSavingUserDefaults(false);
    }
  };

  return {
    sessionDetail,
    setSessionDetail,
    messages,
    setMessages,
    activeRun,
    setActiveRun,
    latestRun,
    activeWaitingRun,
    setActiveWaitingRun,
    gitStatus,
    setGitStatus,
    loadingMessages,
    loadedSessionId,
    loadSessionDetail,
    fetchGitStatus,
    resetForEmptySession,
    handleSubmitWaitingAnswers,
    handleCancelWaitingRun,
    isSessionSettingsOpen,
    setIsSessionSettingsOpen,
    sessionSelectedTools,
    setSessionSelectedTools,
    sessionTitleDraft,
    setSessionTitleDraft,
    orchestratorProviderDraft,
    orchestratorModelDraft,
    setOrchestratorModelDraft,
    handleOrchestratorProviderChange,
    savingSessionTools,
    openSessionSettings,
    handleSaveSessionTools,
    handleResetSessionTools,
    isUserDefaultsOpen,
    setIsUserDefaultsOpen,
    userDefaults,
    userDefaultsSelectedTools,
    setUserDefaultsSelectedTools,
    loadingUserDefaults,
    savingUserDefaults,
    handleOpenUserDefaults,
    handleSaveUserDefaults,
  };
}
