import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createAgent,
  createAgentSession,
  deleteAgent,
  deleteAgentSession,
  getAgentSessionDetail,
  listAgents,
  listAgentSessions,
  listAgentTools,
  streamAgentMessage,
  updateAgent,
} from "../../api/client";
import type {
  Agent,
  AgentMessage,
  AgentSession,
  AgentStreamEvent,
  AgentTool,
} from "../../api/types";
import { ROUTES } from "../../constants/routes";

const SCHEDULE_ASSISTANT_TEMPLATE = {
  name: "予定アシスタント",
  system_prompt:
    "あなたはユーザーの予定・リマインダー・メモを整理し、次に行うべきアクションをわかりやすく助言する予定アシスタントです。必要に応じてカレンダーやリマインダーを読み取り、作成提案を行います。",
  provider: "",
  model: "",
  tool_ids: [
    "calendar_read",
    "reminders_read",
    "calendar_create_proposal",
    "reminder_create_proposal",
    "vault_search",
    "vault_read_file",
  ],
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [availableTools, setAvailableTools] = useState<AgentTool[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);

  // Agent form state
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [formName, setFormName] = useState("");
  const [formPrompt, setFormPrompt] = useState("");
  const [formProvider, setFormProvider] = useState("");
  const [formModel, setFormModel] = useState("");
  const [formToolIds, setFormToolIds] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Chat stream state
  const [inputText, setInputText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [hitlLinks, setHitlLinks] = useState<string[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);

  // Modal delete targets
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);
  const [sessionToDelete, setSessionToDelete] = useState<AgentSession | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Load agents & catalog tools on mount
  useEffect(() => {
    loadAgentsAndTools();
  }, []);

  const loadAgentsAndTools = async () => {
    setActionError(null);
    try {
      const [agRes, toolRes] = await Promise.all([
        listAgents(),
        listAgentTools(),
      ]);
      setAgents(agRes.agents);
      setAvailableTools(toolRes.tools);
      if (agRes.agents.length > 0 && !selectedAgentId) {
        setSelectedAgentId(agRes.agents[0].agent_id);
      }
    } catch (e: any) {
      setActionError(e.message || "エージェントまたはツールの読み込みに失敗しました。");
    }
  };

  // Load sessions when selected agent changes
  useEffect(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setStreamingText("");

    if (!selectedAgentId) {
      setSessions([]);
      setSelectedSessionId(null);
      setMessages([]);
      return;
    }
    loadSessions(selectedAgentId);
  }, [selectedAgentId]);

  const loadSessions = async (agentId: string) => {
    setActionError(null);
    try {
      const res = await listAgentSessions(agentId);
      setSessions(res.sessions);
      if (res.sessions.length > 0) {
        setSelectedSessionId(res.sessions[0].session_id);
      } else {
        setSelectedSessionId(null);
        setMessages([]);
      }
    } catch (e: any) {
      setActionError(e.message || "会話履歴の読み込みに失敗しました。");
    }
  };

  // Load session detail messages when session changes
  useEffect(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsStreaming(false);
    setStreamingText("");

    if (!selectedSessionId) {
      setMessages([]);
      return;
    }
    loadSessionDetail(selectedSessionId);
    setHitlLinks([]);
  }, [selectedSessionId]);

  const loadSessionDetail = async (sessionId: string) => {
    setActionError(null);
    try {
      const detail = await getAgentSessionDetail(sessionId);
      setMessages(detail.messages);
      setChatError(null);
    } catch (e: any) {
      setChatError(e.message || "セッション詳細の読み込みに失敗しました。");
    }
  };

  // Modal ESC listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAgentToDelete(null);
        setSessionToDelete(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Cleanup abort controller on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, streamingText]);

  const activeAgent = agents.find((a) => a.agent_id === selectedAgentId);

  // Agent Form Actions
  const handleOpenCreateForm = () => {
    setIsCreatingAgent(true);
    setIsEditingAgent(false);
    setFormName("");
    setFormPrompt("");
    setFormProvider("");
    setFormModel("");
    setFormToolIds([]);
    setFormError(null);
    setActionError(null);
  };

  const handleOpenEditForm = (agent: Agent) => {
    setIsEditingAgent(true);
    setIsCreatingAgent(false);
    setFormName(agent.name);
    setFormPrompt(agent.system_prompt);
    setFormProvider(agent.provider || "");
    setFormModel(agent.model || "");
    setFormToolIds(agent.tool_ids || []);
    setFormError(null);
    setActionError(null);
  };

  const handleApplyTemplate = () => {
    setFormName(SCHEDULE_ASSISTANT_TEMPLATE.name);
    setFormPrompt(SCHEDULE_ASSISTANT_TEMPLATE.system_prompt);
    setFormProvider(SCHEDULE_ASSISTANT_TEMPLATE.provider);
    setFormModel(SCHEDULE_ASSISTANT_TEMPLATE.model);
    setFormToolIds(SCHEDULE_ASSISTANT_TEMPLATE.tool_ids);
  };

  const handleSaveAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setActionError(null);
    try {
      if (isCreatingAgent) {
        const res = await createAgent({
          name: formName,
          system_prompt: formPrompt,
          provider: formProvider || undefined,
          model: formModel || undefined,
          tool_ids: formToolIds,
        });
        setAgents([res.agent, ...agents]);
        setSelectedAgentId(res.agent.agent_id);
      } else if (isEditingAgent && selectedAgentId) {
        const res = await updateAgent(selectedAgentId, {
          name: formName,
          system_prompt: formPrompt,
          provider: formProvider,
          model: formModel,
          tool_ids: formToolIds,
        });
        setAgents(
          agents.map((a) => (a.agent_id === selectedAgentId ? res.agent : a))
        );
      }
      setIsCreatingAgent(false);
      setIsEditingAgent(false);
    } catch (err: any) {
      setFormError(err.message || "エージェントの保存に失敗しました。");
    }
  };

  const handleDeleteAgentConfirm = async () => {
    if (!agentToDelete) return;
    setActionError(null);
    try {
      await deleteAgent(agentToDelete.agent_id);
      const remaining = agents.filter((a) => a.agent_id !== agentToDelete.agent_id);
      setAgents(remaining);
      setAgentToDelete(null);
      if (selectedAgentId === agentToDelete.agent_id) {
        setSelectedAgentId(remaining.length > 0 ? remaining[0].agent_id : null);
      }
    } catch (e: any) {
      setActionError("エージェントの削除に失敗しました: " + e.message);
      setAgentToDelete(null);
    }
  };

  // Session Actions
  const handleCreateSession = async () => {
    if (!selectedAgentId) return;
    setActionError(null);
    try {
      const res = await createAgentSession(selectedAgentId);
      setSessions([res.session, ...sessions]);
      setSelectedSessionId(res.session.session_id);
    } catch (e: any) {
      setActionError("セッション作成に失敗しました: " + e.message);
    }
  };

  const handleDeleteSessionConfirm = async () => {
    if (!sessionToDelete) return;
    setActionError(null);
    try {
      await deleteAgentSession(sessionToDelete.session_id);
      const remaining = sessions.filter(
        (s) => s.session_id !== sessionToDelete.session_id
      );
      setSessions(remaining);
      setSessionToDelete(null);
      if (selectedSessionId === sessionToDelete.session_id) {
        setSelectedSessionId(remaining.length > 0 ? remaining[0].session_id : null);
      }
    } catch (e: any) {
      setActionError("セッション削除に失敗しました: " + e.message);
      setSessionToDelete(null);
    }
  };

  // Send Message & Stream Response
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || !inputText.trim() || isStreaming) return;

    const userText = inputText.trim();
    setInputText("");
    setChatError(null);
    setHitlLinks([]);
    setIsStreaming(true);
    setStreamingText("");

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const controller = new AbortController();
    abortControllerRef.current = controller;

    // Optimistically push user message to UI
    const tempUserMsg: AgentMessage = {
      message_id: `temp_${Date.now()}`,
      session_id: selectedSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: userText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    try {
      await streamAgentMessage(
        selectedSessionId,
        userText,
        (event: AgentStreamEvent) => {
          if (event.type === "text") {
            setStreamingText((prev) => prev + event.delta);
          } else if (event.type === "done") {
            setIsStreaming(false);
            setStreamingText("");
            loadSessionDetail(selectedSessionId);
            if (event.hitl_run_ids && event.hitl_run_ids.length > 0) {
              setHitlLinks(event.hitl_run_ids);
            }
          } else if (event.type === "error") {
            setIsStreaming(false);
            setChatError(event.error || "エラーが発生しました。");
          }
        },
        controller.signal
      );
    } catch (err: any) {
      if (err.name === "AbortError") return;
      setIsStreaming(false);
      setChatError(err.message || "メッセージの送信に失敗しました。");
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50 lg:flex-row">
      {/* Left Pane: Agent List */}
      <div className="flex w-full flex-col border-r border-slate-200 bg-white lg:w-64">
        <div className="flex items-center justify-between border-b border-slate-200 p-3">
          <h2 className="text-sm font-semibold text-slate-900">AIエージェント</h2>
          <button
            type="button"
            onClick={handleOpenCreateForm}
            className="rounded cursor-pointer bg-slate-900 px-2.5 py-1 text-xs text-white hover:bg-slate-800"
          >
            ＋ 新規作成
          </button>
        </div>
        {actionError && (
          <div className="m-2 rounded-lg bg-red-50 p-2 text-xs text-red-600">
            {actionError}
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {agents.length === 0 ? (
            <p className="p-3 text-center text-xs text-slate-500">
              エージェントが登録されていません。
            </p>
          ) : (
            agents.map((agent) => (
              <button
                key={agent.agent_id}
                type="button"
                onClick={() => {
                  setSelectedAgentId(agent.agent_id);
                  setIsCreatingAgent(false);
                  setIsEditingAgent(false);
                }}
                className={`w-full cursor-pointer rounded-lg px-3 py-2 text-left text-xs transition ${
                  selectedAgentId === agent.agent_id &&
                  !isCreatingAgent &&
                  !isEditingAgent
                    ? "bg-slate-900 text-white font-medium"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <div className="truncate font-semibold">{agent.name}</div>
                <div className="truncate text-[10px] opacity-75">
                  {agent.tool_ids.length} ツール | {agent.provider || "既定"}
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {isCreatingAgent || isEditingAgent ? (
          /* Agent Create / Edit Form */
          <div className="flex-1 overflow-y-auto p-6">
            <div className="mx-auto max-w-2xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="text-base font-semibold text-slate-900">
                  {isCreatingAgent
                    ? "新規エージェント作成"
                    : "エージェント設定編集"}
                </h3>
                <button
                  type="button"
                  onClick={handleApplyTemplate}
                  className="rounded cursor-pointer border border-indigo-200 bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-100"
                >
                  予定アシスタントテンプレートを適用
                </button>
              </div>

              {formError && (
                <div className="mb-4 rounded-lg bg-red-50 p-3 text-xs text-red-600">
                  {formError}
                </div>
              )}

              <form onSubmit={handleSaveAgent} className="space-y-4 text-xs">
                <div>
                  <label className="block font-medium text-slate-700 mb-1">
                    エージェント名 <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="例: 予定アシスタント"
                    className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block font-medium text-slate-700 mb-1">
                    システムプロンプト <span className="text-red-500">*</span>
                  </label>
                  <textarea
                    required
                    rows={4}
                    value={formPrompt}
                    onChange={(e) => setFormPrompt(e.target.value)}
                    placeholder="エージェントの役割や振る舞いを指示します"
                    className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">
                      LLM Provider (任意)
                    </label>
                    <input
                      type="text"
                      value={formProvider}
                      onChange={(e) => setFormProvider(e.target.value)}
                      placeholder="空欄でアプリ既定値"
                      className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-slate-700 mb-1">
                      LLM Model (任意)
                    </label>
                    <input
                      type="text"
                      value={formModel}
                      onChange={(e) => setFormModel(e.target.value)}
                      placeholder="空欄でアプリ既定値"
                      className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                    />
                  </div>
                </div>
                <p className="text-[11px] text-slate-500">
                  ※ Provider / Model が空欄の場合はアプリ全体の既定LLM設定が自動適用されます。
                </p>

                <div>
                  <label className="block font-medium text-slate-700 mb-2">
                    利用可能ツール選択
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 border border-slate-200 rounded-md p-3 max-h-48 overflow-y-auto">
                    {availableTools.map((t) => {
                      const checked = formToolIds.includes(t.tool_id);
                      return (
                        <label
                          key={t.tool_id}
                          className="flex items-start gap-2 text-xs cursor-pointer hover:bg-slate-50 p-1 rounded"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setFormToolIds([...formToolIds, t.tool_id]);
                              } else {
                                setFormToolIds(
                                  formToolIds.filter((id) => id !== t.tool_id)
                                );
                              }
                            }}
                            className="mt-0.5 cursor-pointer"
                          />
                          <div>
                            <span className="font-semibold text-slate-800">
                              {t.name}
                            </span>
                            <p className="text-[10px] text-slate-500">
                              {t.description}
                            </p>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setIsCreatingAgent(false);
                      setIsEditingAgent(false);
                    }}
                    className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
                  >
                    キャンセル
                  </button>
                  <button
                    type="submit"
                    className="rounded cursor-pointer bg-slate-900 px-4 py-1.5 text-xs text-white hover:bg-slate-800 font-medium"
                  >
                    保存する
                  </button>
                </div>
              </form>
            </div>
          </div>
        ) : activeAgent ? (
          /* Active Agent Workspace */
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-900">
                  {activeAgent.name}
                </h3>
                <p className="text-[11px] text-slate-500 truncate max-w-lg">
                  {activeAgent.system_prompt}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleOpenEditForm(activeAgent)}
                  className="rounded cursor-pointer border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:bg-slate-50"
                >
                  設定編集
                </button>
                <button
                  type="button"
                  onClick={() => setAgentToDelete(activeAgent)}
                  className="rounded cursor-pointer border border-red-200 bg-red-50 px-2.5 py-1 text-xs text-red-600 hover:bg-red-100"
                >
                  削除
                </button>
              </div>
            </div>

            {/* Sessions Bar */}
            <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-100 px-4 py-2 overflow-x-auto">
              <span className="text-[11px] font-medium text-slate-500 shrink-0">
                会話履歴:
              </span>
              {sessions.map((s) => (
                <div
                  key={s.session_id}
                  className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition ${
                    selectedSessionId === s.session_id
                      ? "bg-slate-900 text-white font-medium"
                      : "bg-white text-slate-700 border border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => setSelectedSessionId(s.session_id)}
                    className="truncate max-w-[120px] cursor-pointer"
                  >
                    {s.title}
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSessionToDelete(s);
                    }}
                    className="text-[10px] opacity-60 hover:opacity-100 cursor-pointer"
                    aria-label="会話削除"
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={handleCreateSession}
                className="rounded-full cursor-pointer border border-dashed border-slate-400 px-2.5 py-1 text-xs text-slate-600 hover:bg-white shrink-0"
              >
                ＋ 新しい会話
              </button>
            </div>

            {/* Chat Messages View */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 && !isStreaming ? (
                <div className="flex h-full items-center justify-center text-xs text-slate-400">
                  メッセージを入力して会話を開始してください。
                </div>
              ) : (
                messages.map((m) => (
                  <div
                    key={m.message_id}
                    className={`flex ${
                      m.role === "user" ? "justify-end" : "justify-start"
                    }`}
                  >
                    <div
                      className={`max-w-xl rounded-2xl px-4 py-2.5 text-xs shadow-sm whitespace-pre-wrap ${
                        m.role === "user"
                          ? "bg-slate-900 text-white"
                          : "bg-white border border-slate-200 text-slate-800"
                      }`}
                    >
                      {m.content}
                    </div>
                  </div>
                ))
              )}

              {/* Live Streaming Response Chunk */}
              {isStreaming && (
                <div className="flex justify-start">
                  <div className="max-w-xl rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-800 shadow-sm whitespace-pre-wrap">
                    {streamingText || "考え中…"}
                  </div>
                </div>
              )}

              {/* HITL Run Links Alert */}
              {hitlLinks.length > 0 && (
                <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800">
                  <div className="font-semibold mb-1">
                    承認待ちの登録申請が作成されました
                  </div>
                  <p className="mb-2 text-[11px]">
                    エージェントがカレンダー／リマインダー作成提案を登録しました。確認待ち画面で確認・承認を行ってください。
                  </p>
                  <Link
                    to={ROUTES.HITL}
                    className="inline-flex items-center gap-1 font-semibold text-yellow-900 underline hover:text-yellow-700 cursor-pointer"
                  >
                    → 確認待ち画面へ移動する
                  </Link>
                </div>
              )}

              {/* Chat Error */}
              {chatError && (
                <div className="rounded-lg bg-red-50 p-3 text-xs text-red-600">
                  {chatError}
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Input Footer */}
            <form
              onSubmit={handleSendMessage}
              className="border-t border-slate-200 bg-white p-3 flex gap-2"
            >
              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                disabled={isStreaming || !selectedSessionId}
                placeholder={
                  selectedSessionId
                    ? "メッセージを入力…"
                    : "上の「＋ 新しい会話」をクリックしてください"
                }
                className="flex-1 rounded-lg border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none disabled:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              <button
                type="submit"
                disabled={isStreaming || !inputText.trim() || !selectedSessionId}
                className="rounded-lg bg-slate-900 px-4 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                送信
              </button>
            </form>
          </div>
        ) : (
          /* Empty State */
          <div className="flex h-full items-center justify-center text-xs text-slate-500">
            左側のメニューからエージェントを選択するか、「＋ 新規作成」ボタンを押してください。
          </div>
        )}
      </div>

      {/* Delete Agent Modal */}
      {agentToDelete && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setAgentToDelete(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-xl bg-white p-5 shadow-lg space-y-3"
          >
            <h4 className="text-sm font-semibold text-slate-900">
              エージェントの削除確認
            </h4>
            <p className="text-xs text-slate-600">
              「{agentToDelete.name}
              」を削除してもよろしいですか？関連するすべての会話セッション、メッセージ履歴、および実行記録も削除されます。
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setAgentToDelete(null)}
                className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleDeleteAgentConfirm}
                className="rounded cursor-pointer bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-700 font-medium"
              >
                削除する
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete Session Modal */}
      {sessionToDelete && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setSessionToDelete(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-sm rounded-xl bg-white p-5 shadow-lg space-y-3"
          >
            <h4 className="text-sm font-semibold text-slate-900">
              会話履歴の削除確認
            </h4>
            <p className="text-xs text-slate-600">
              「{sessionToDelete.title}
              」を削除してもよろしいですか？含まれる全メッセージおよび実行記録が削除されます。
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setSessionToDelete(null)}
                className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleDeleteSessionConfirm}
                className="rounded cursor-pointer bg-red-600 px-3 py-1.5 text-xs text-white hover:bg-red-700 font-medium"
              >
                削除する
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
