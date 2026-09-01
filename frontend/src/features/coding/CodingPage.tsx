import { useEffect, useRef, useState } from "react";
import {
  listCodingProjects,
  listCodingSessions,
  createCodingSession,
  getCodingSessionDetail,
  deleteCodingSession,
  cancelCodingRun,
  streamCodingMessage,
  type CodingProjectItem,
  type CodingSession,
  type CodingMessage,
  type CodingRun,
  type CodingSseEvent,
} from "../../api/coding";
import MarkdownPreview from "../../components/MarkdownPreview";
import { formatDateTime } from "../../utils/date";
import {
  getChatInputPlaceholder,
  shouldSendOnEnter,
  useChatSendMode,
} from "../settings/chatSendMode";

export default function CodingPage() {
  const [projects, setProjects] = useState<CodingProjectItem[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [sessions, setSessions] = useState<CodingSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const [messages, setMessages] = useState<CodingMessage[]>([]);
  const [activeRun, setActiveRun] = useState<CodingRun | null>(null);
  const [latestRun, setLatestRun] = useState<CodingRun | null>(null);

  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // New session modal state
  const [isNewSessionModalOpen, setIsNewSessionModalOpen] = useState(false);
  const [newSessionBackend, setNewSessionBackend] = useState<"codex" | "opencode">("codex");
  const [newSessionTitle, setNewSessionTitle] = useState("");
  const [creatingSession, setCreatingSession] = useState(false);

  // Chat input and streaming state
  const [inputContent, setInputContent] = useState("");
  const [chatSendMode] = useChatSendMode();
  const [isStreaming, setIsStreaming] = useState(false);
  const [activePhaseText, setActivePhaseText] = useState<string | null>(null);
  const [workerState, setWorkerState] = useState<{
    status: "idle" | "running" | "done";
    attempt?: number;
    backend?: string;
    output?: string;
    error?: string | null;
  }>({ status: "idle" });

  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);

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

  // Auto-scroll on new messages / phase change
  useEffect(() => {
    if (typeof messageEndRef.current?.scrollIntoView === "function") {
      messageEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, activePhaseText, workerState]);

  // Load projects on mount
  useEffect(() => {
    loadProjects();
  }, []);

  const loadProjects = async () => {
    setLoadingProjects(true);
    setError(null);
    try {
      const data = await listCodingProjects();
      setProjects(data);
      if (data.length > 0 && selectedProjectId === null) {
        setSelectedProjectId(data[0].project.project_id);
      }
    } catch (e: any) {
      setError(e.message || "プロジェクト一覧の取得に失敗しました");
    } finally {
      setLoadingProjects(false);
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
  }, [selectedProjectId]);

  const loadSessions = async (projectId: number) => {
    setLoadingSessions(true);
    try {
      const data = await listCodingSessions(projectId);
      setSessions(data);
      if (data.length > 0) {
        setSelectedSessionId(data[0].session_id);
      } else {
        setSelectedSessionId(null);
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

  // Load messages & run details when selected session changes
  useEffect(() => {
    if (!selectedSessionId) {
      setMessages([]);
      setActiveRun(null);
      setLatestRun(null);
      return;
    }
    loadSessionDetail(selectedSessionId);
  }, [selectedSessionId]);

  const loadSessionDetail = async (sessionId: string) => {
    setLoadingMessages(true);
    try {
      const data = await getCodingSessionDetail(sessionId);
      setMessages(data.messages);
      setActiveRun(data.active_run);
      setLatestRun(data.latest_run);
    } catch (e: any) {
      setError(e.message || "セッション詳細の取得に失敗しました");
    } finally {
      setLoadingMessages(false);
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
      setSelectedSessionId(session.session_id);
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

    const promptText = inputContent.trim();
    setInputContent("");
    setIsStreaming(true);
    setActivePhaseText("依頼を検討中...");
    setWorkerState({ status: "idle" });
    setError(null);

    // Optimistically add user message to list
    const tempUserMsgId = `temp_${Date.now()}`;
    const tempUserMsg: CodingMessage = {
      message_id: tempUserMsgId,
      session_id: selectedSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: promptText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      await streamCodingMessage(selectedSessionId, promptText, (event: CodingSseEvent) => {
        if (event.event === "start") {
          setActiveRun({
            run_id: event.run_id,
            session_id: selectedSessionId,
            user_message_id: tempUserMsg.message_id,
            orchestrator_message_id: null,
            worker_message_id: null,
            status: "running",
            dirty_tree_at_start: event.dirty_summary,
            error_message: null,
            started_at: new Date().toISOString(),
            finished_at: null,
          });
        } else if (event.event === "orchestrator_start") {
          setActivePhaseText(
            event.phase === "initial" ? "依頼を検討中..." : "CLI結果を確認中..."
          );
        } else if (event.event === "orchestrator_message") {
          setActivePhaseText(null);
          setMessages((prev) => {
            if (prev.some((m) => m.message_id === event.message.message_id)) return prev;
            return [...prev, event.message];
          });
        } else if (event.event === "worker_start") {
          setActivePhaseText(null);
          setWorkerState({
            status: "running",
            attempt: event.attempt,
            backend: event.backend,
          });
        } else if (event.event === "worker_done") {
          setWorkerState({
            status: "done",
            attempt: event.attempt,
            output: event.message.content,
            error: event.error,
          });
          setMessages((prev) => {
            if (prev.some((m) => m.message_id === event.message.message_id)) return prev;
            return [...prev, event.message];
          });
        } else if (event.event === "cancelled") {
          setError("キャンセルされました");
          setActivePhaseText(null);
          setWorkerState({ status: "idle" });
        } else if (event.event === "error") {
          setError(event.message);
          setActivePhaseText(null);
          setWorkerState({ status: "idle" });
        } else if (event.event === "done") {
          setIsStreaming(false);
          setActivePhaseText(null);
          setWorkerState({ status: "idle" });
          // Reload full session state to ensure complete synchronization
          loadSessionDetail(selectedSessionId);
        }
      });
    } catch (err: any) {
      setError(err.message || "メッセージの送信に失敗しました");
      setInputContent(promptText);
      setMessages((prev) => prev.filter((m) => m.message_id !== tempUserMsgId));
    } finally {
      setIsStreaming(false);
      setActivePhaseText(null);
      setWorkerState({ status: "idle" });
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeSend();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (shouldSendOnEnter(e, chatSendMode)) {
      e.preventDefault();
      void executeSend();
    }
  };

  const codingPlaceholder = getChatInputPlaceholder(chatSendMode, "指示・質問を入力");

  const handleCancelRun = async () => {
    const runId = activeRun?.run_id || latestRun?.run_id;
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

  const selectedProjectItem = projects.find(
    (p) => p.project.project_id === selectedProjectId,
  );
  const selectedSession = sessions.find((s) => s.session_id === selectedSessionId);

  const currentRun = activeRun || latestRun;

  return (
    <div className="flex h-full w-full overflow-hidden bg-slate-50">
      {/* Pane 1: Project List */}
      <div className="flex w-64 flex-col border-r border-slate-200 bg-white">
        <div className="border-b border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-800">プロジェクト</h2>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {loadingProjects ? (
            <div className="p-3 text-xs text-slate-500">読み込み中...</div>
          ) : projects.length === 0 ? (
            <div className="p-3 text-xs text-slate-500">プロジェクトがありません</div>
          ) : (
            <div className="space-y-1">
              {projects.map((item) => {
                const isSelected = item.project.project_id === selectedProjectId;
                return (
                  <button
                    key={item.project.project_id}
                    type="button"
                    onClick={() => setSelectedProjectId(item.project.project_id)}
                    className={`w-full rounded px-3 py-2 text-left text-xs transition-colors ${
                      isSelected
                        ? "bg-slate-900 font-medium text-white"
                        : "text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="truncate">{item.project.display_name}</span>
                      <span
                        className={`ml-1 rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          item.is_valid_git_repo
                            ? isSelected
                              ? "bg-slate-700 text-slate-200"
                              : "bg-emerald-100 text-emerald-800"
                            : "bg-amber-100 text-amber-800"
                        }`}
                      >
                        {item.is_valid_git_repo ? "Git OK" : "無効"}
                      </span>
                    </div>
                    {item.project.domain && (
                      <div className={`mt-0.5 text-[10px] ${isSelected ? "text-slate-300" : "text-slate-400"}`}>
                        {item.project.domain} • {item.project.status}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Pane 2: Session List */}
      <div className="flex w-72 flex-col border-r border-slate-200 bg-white">
        <div className="flex items-center justify-between border-b border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-800">セッション</h2>
          {selectedProjectItem && (
            <button
              type="button"
              disabled={!selectedProjectItem.is_valid_git_repo}
              onClick={() => setIsNewSessionModalOpen(true)}
              className="rounded bg-slate-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-300"
              title={
                !selectedProjectItem.is_valid_git_repo
                  ? "Gitリポジトリが無効なためセッションを作成できません"
                  : "新規セッション作成"
              }
            >
              + 新規
            </button>
          )}
        </div>

        {selectedProjectItem && !selectedProjectItem.is_valid_git_repo && (
          <div className="m-2 rounded bg-amber-50 p-2.5 text-xs text-amber-800 border border-amber-200">
            <strong>Gitリポジトリが無効です</strong>
            <p className="mt-1 text-[11px]">
              {selectedProjectItem.error_message || "project_path がGitルートではありません"}
            </p>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-2">
          {loadingSessions ? (
            <div className="p-3 text-xs text-slate-500">セッション読み込み中...</div>
          ) : sessions.length === 0 ? (
            <div className="p-3 text-xs text-slate-500">
              セッションがありません。「+ 新規」から作成してください。
            </div>
          ) : (
            <div className="space-y-1">
              {sessions.map((sess) => {
                const isSelected = sess.session_id === selectedSessionId;
                const dateStr = sess.created_at ? new Date(sess.created_at).toLocaleDateString() : "";
                return (
                  <div
                    key={sess.session_id}
                    data-selected={isSelected}
                    onClick={() => setSelectedSessionId(sess.session_id)}
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
              })}
            </div>
          )}
        </div>
      </div>

      {/* Pane 3: Conversation */}
      <div className="flex flex-1 flex-col overflow-hidden bg-slate-50">
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
          <div className="flex flex-1 items-center justify-center text-xs text-slate-400">
            セッションを選択するか、新規セッションを作成してください
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
              <div>
                <h1 className="text-sm font-semibold text-slate-800">{selectedSession.title}</h1>
                <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium uppercase text-slate-700">
                    {selectedSession.backend}
                  </span>
                  <span>{selectedSession.repo_path}</span>
                </div>
              </div>

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

            {/* Dirty tree warning banner if run started with uncommitted changes */}
            {currentRun?.dirty_tree_at_start && (
              <div className="bg-amber-50 px-4 py-2 text-xs text-amber-800 border-b border-amber-200">
                <span className="font-semibold">⚠️ 開始時に未コミットの変更があります:</span>
                <pre className="mt-1 max-h-20 overflow-y-auto text-[10px] font-mono bg-amber-100/50 p-1.5 rounded">
                  {currentRun.dirty_tree_at_start}
                </pre>
              </div>
            )}

            {/* Message Area */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
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
                  <div key={msg.message_id} className="space-y-1">
                    {msg.role === "user" && (
                      <div className="flex justify-end">
                        <div className="max-w-2xl rounded-2xl bg-slate-900 px-4 py-2.5 text-xs text-white">
                          <p className="whitespace-pre-wrap">{msg.content}</p>
                        </div>
                      </div>
                    )}

                    {msg.role === "orchestrator" && (
                      <>
                        <div className="flex justify-start">
                          <div className="max-w-2xl rounded-2xl bg-white border border-slate-200 p-4 text-xs text-slate-800 shadow-sm">
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

                    {msg.role === "worker" && (
                      <>
                        <div className="flex justify-start">
                          <div className="w-full max-w-2xl">
                            <details className="rounded-xl border border-slate-200 bg-slate-900 text-slate-100 text-xs shadow-sm overflow-hidden group">
                              <summary className="flex cursor-pointer items-center justify-between px-4 py-2.5 bg-slate-800 font-mono text-[11px] hover:bg-slate-700">
                                <span>CLI Worker 最終返答 ({selectedSession.backend})</span>
                                <span className="text-slate-400 text-[10px]">クリックで展開/折りたたみ</span>
                              </summary>
                              <div className="p-4 overflow-x-auto max-h-96">
                                <MarkdownPreview content={msg.content} variant="dark" />
                              </div>
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
                                  d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-2M8 5a2 2 0 002 2h4a2 2 0 002-2M8 5a2 2 0 012-2h4a2 2 0 012 2"
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

              <div ref={messageEndRef} />
            </div>

            {/* Input Form */}
            <div className="border-t border-slate-200 bg-white p-3">
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
                  placeholder="例: リファクタリング作業"
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
                    onClick={() => setNewSessionBackend("codex")}
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
                    onClick={() => setNewSessionBackend("opencode")}
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
                className="rounded bg-slate-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-slate-800 cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-slate-300"
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
