import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createCodingSession,
  deleteCodingSession,
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

  // New session creation state (no dialog: created immediately with empty title)
  const [creatingSession, setCreatingSession] = useState(false);

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
    if (selectedProjectId === null || creatingSession) return;
    setCreatingSession(true);
    try {
      // The server assigns the config-derived default model at creation.
      const session = await createCodingSession(
        selectedProjectId,
        undefined, // title: empty by default, editable later via conversation settings
        undefined, // toolIds: keep user defaults
      );
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
    creatingSession,
    handleCreateSession,
    handleDeleteSession,
  };
}
