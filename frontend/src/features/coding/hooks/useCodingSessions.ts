import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createCodingSession,
  deleteCodingSession,
  getCodingConfig,
  listCodingSessions,
  type CodingSession,
} from "../../../api/coding";

interface UseCodingSessionsOptions {
  selectedProjectId: number | null;
  onError: (message: string | null) => void;
  /** セッション一覧が空になった際の会話側リセット処理。 */
  onEmptySessions: () => void;
}

/** セッション一覧・選択・作成・削除と新規作成モーダルの状態を管理する。 */
export function useCodingSessions({
  selectedProjectId,
  onError,
  onEmptySessions,
}: UseCodingSessionsOptions) {
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [searchParams, setSearchParams] = useSearchParams();

  // New session modal state
  const [isNewSessionModalOpen, setIsNewSessionModalOpen] = useState(false);
  const [newSessionBackend, setNewSessionBackend] = useState<"codex" | "opencode">("opencode");
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [creatingSession, setCreatingSession] = useState(false);
  const backendManuallySelected = useRef(false);

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

  const syncSessionUrl = (
    sessionId: string | null,
    setParams: typeof setSearchParams,
  ) => {
    setParams(
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
  };

  const selectSession = (sessionId: string | null) => {
    setSelectedSessionId(sessionId);
    syncSessionUrl(sessionId, setSearchParams);
  };

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
            syncSessionUrl(null, setSearchParams);
          } else if (!urlSessionId) {
            syncSessionUrl(fallback, setSearchParams);
          }
        }
      } else {
        setSelectedSessionId(null);
        syncSessionUrl(null, setSearchParams);
        onEmptySessions();
      }
    } catch (e: any) {
      setSessions([]);
      setSelectedSessionId(null);
      onError(e.message || "セッション一覧の取得に失敗しました");
    } finally {
      setLoadingSessions(false);
    }
  };

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
      onError(e.message || "セッションの作成に失敗しました");
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
      onError(err.message || "セッションの削除に失敗しました");
    }
  };

  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);

  return {
    sessions,
    setSessions,
    selectedSessionId,
    selectedSession,
    loadingSessions,
    loadSessions,
    selectSession,
    syncSessionUrl: (sessionId: string | null) => syncSessionUrl(sessionId, setSearchParams),
    isNewSessionModalOpen,
    setIsNewSessionModalOpen,
    newSessionBackend,
    setNewSessionBackend,
    newSessionTitle,
    setNewSessionTitle,
    creatingSession,
    backendManuallySelected,
    handleCreateSession,
    handleDeleteSession,
  };
}
