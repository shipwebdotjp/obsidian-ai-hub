import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  AgentLiveToolCall,
  AgentMessage,
  AgentRun,
  AgentSession,
  AgentStreamEvent,
  AgentTool,
  AgentToolCall,
} from "../../api/types";
import { ROUTES } from "../../constants/routes";
import MarkdownPreview from "../../components/MarkdownPreview";
import { formatDateTime } from "../../utils/date";

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

// keep in sync with runtime.py _LIVE_RESULT_MAX_CHARS (DB is 20000)
const LIVE_RESULT_MAX_CHARS = 2000;

const LIVE_STATUS_CONFIG: Record<AgentLiveToolCall["status"], { label: string; cls: string }> = {
  succeeded: { label: "成功", cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  failed: { label: "失敗", cls: "bg-rose-50 text-rose-700 border-rose-200" },
  running: { label: "実行中…", cls: "bg-amber-50 text-amber-700 border-amber-200" },
  preparing: { label: "準備中…", cls: "bg-blue-50 text-blue-700 border-blue-200" },
};

function matchesLiveToolCall(
  toolCall: AgentLiveToolCall,
  callKey?: string,
  callId?: string,
): boolean {
  return (
    (Boolean(callKey) && (toolCall.call_key === callKey || toolCall.id === callKey)) ||
    (Boolean(callId) && (toolCall.call_id === callId || toolCall.id === callId))
  );
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [availableTools, setAvailableTools] = useState<AgentTool[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  const [sessions, setSessions] = useState<AgentSession[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);

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
  const [streamingToolCalls, setStreamingToolCalls] = useState<AgentLiveToolCall[]>([]);
  const [streamingPhase, setStreamingPhase] = useState<"thinking" | "tool_preparing" | "tool_running" | null>(null);
  const [streamingIteration, setStreamingIteration] = useState<number | null>(null);
  const [hitlLinks, setHitlLinks] = useState<string[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);

  // Modal delete targets
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);
  const [sessionToDelete, setSessionToDelete] = useState<AgentSession | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamGenerationRef = useRef(0);
  const streamingTextBufferRef = useRef("");
  const streamingTextFrameRef = useRef<number | null>(null);

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

  const getLiveStatusLabel = (s: AgentLiveToolCall["status"]): string => LIVE_STATUS_CONFIG[s].label;
  const getLiveStatusClass = (s: AgentLiveToolCall["status"]): string => LIVE_STATUS_CONFIG[s].cls;

  const [searchParams, setSearchParams] = useSearchParams();
  const sessionIdParam = searchParams.get("session_id");
  // Holds the session_id to honor after sessions are loaded for the resolved agent.
  // Cleared after consumption so subsequent agent switches do not re-select it.
  const pendingSessionIdRef = useRef<string | null>(null);

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

      // Deep link: resolve the agent from the URL's session_id, then let the
      // selectedAgentId effect load the session list and consume pendingSessionIdRef.
      if (sessionIdParam) {
        pendingSessionIdRef.current = sessionIdParam;
        try {
          const detail = await getAgentSessionDetail(sessionIdParam);
          setSelectedAgentId(detail.agent.agent_id);
          return;
        } catch {
          // Stale or invalid session_id: fall back to first agent and clear the param.
          pendingSessionIdRef.current = null;
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
    resetStreamingState();

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
      const target = pendingSessionIdRef.current;
      if (target && res.sessions.some((s) => s.session_id === target)) {
        setSelectedSessionId(target);
      } else if (target) {
        // Target session does not belong to this agent: drop it and fall back.
        pendingSessionIdRef.current = null;
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.delete("session_id");
            return next;
          },
          { replace: true },
        );
        if (res.sessions.length > 0) {
          setSelectedSessionId(res.sessions[0].session_id);
        } else {
          setSelectedSessionId(null);
          setMessages([]);
        }
      } else if (res.sessions.length > 0) {
        setSelectedSessionId(res.sessions[0].session_id);
      } else {
        setSelectedSessionId(null);
        setMessages([]);
      }
      pendingSessionIdRef.current = null;
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
    resetStreamingState();

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
      setRuns(detail.runs || []);
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
      invalidatePendingStreamingText();
    };
  }, [invalidatePendingStreamingText]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, streamingText, streamingToolCalls, streamingPhase, streamingIteration]);

  const activeAgent = agents.find((a) => a.agent_id === selectedAgentId);
  const displayedStreamingPhase = streamingToolCalls.some(
    (toolCall) => toolCall.status === "running"
  )
    ? "tool_running"
    : streamingToolCalls.some((toolCall) => toolCall.status === "preparing")
      ? "tool_preparing"
      : streamingPhase;

  // Memoize assistant_message_id -> run so O(N*M) lookup becomes O(N) per render.
  // `runs` is replaced wholesale by setRuns, so a single useMemo key is enough.
  const runsByMessageId = useMemo(() => {
    const map = new Map<string, AgentRun>();
    for (const r of runs) {
      if (r.assistant_message_id) map.set(r.assistant_message_id, r);
    }
    return map;
  }, [runs]);

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
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("session_id", res.session.session_id);
          return next;
        },
        { replace: true },
      );
    } catch (e: any) {
      setActionError("セッション作成に失敗しました: " + e.message);
    }
  };

  const handleDeleteSessionConfirm = async () => {
    if (!sessionToDelete) return;
    const wasSelected = selectedSessionId === sessionToDelete.session_id;
    setActionError(null);
    try {
      await deleteAgentSession(sessionToDelete.session_id);
      const remaining = sessions.filter(
        (s) => s.session_id !== sessionToDelete.session_id
      );
      setSessions(remaining);
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
    } catch (e: any) {
      setActionError("セッション削除に失敗しました: " + e.message);
      setSessionToDelete(null);
    }
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

  // Send Message & Stream Response
  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedSessionId || !inputText.trim() || isStreaming) return;

    const streamSessionId = selectedSessionId;
    const userText = inputText.trim();
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    invalidatePendingStreamingText();
    const streamGeneration = streamGenerationRef.current;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setInputText("");
    setChatError(null);
    setHitlLinks([]);
    setIsStreaming(true);
    setStreamingText("");
    setStreamingToolCalls([]);
    setStreamingPhase("thinking");
    setStreamingIteration(null);

    // Optimistically push user message to UI
    const tempUserMsg: AgentMessage = {
      message_id: `temp_${Date.now()}`,
      session_id: streamSessionId,
      sequence: messages.length + 1,
      role: "user",
      content: userText,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);

    const isCurrentStream = () => (
      streamGeneration === streamGenerationRef.current &&
      abortControllerRef.current === controller
    );
    let receivedTerminalEvent = false;

    try {
      await streamAgentMessage(
        streamSessionId,
        userText,
        (event: AgentStreamEvent) => {
          if (!isCurrentStream()) return;

          if (event.type === "thinking") {
            setStreamingPhase("thinking");
            setStreamingIteration(event.iteration);
          } else if (event.type === "tool_call_detected") {
            if (!event.call_key || !event.tool_name) return;
            setStreamingPhase("tool_preparing");
            setStreamingIteration(event.iteration);
            setStreamingToolCalls((previous) => {
              if (previous.some((toolCall) => matchesLiveToolCall(toolCall, event.call_key))) {
                return previous;
              }
              return [
                ...previous,
                {
                  id: event.call_key,
                  call_key: event.call_key,
                  tool_name: event.tool_name,
                  args: {},
                  result: "",
                  status: "preparing",
                  hitl_run_id: null,
                  error: null,
                  iteration: event.iteration,
                },
              ];
            });
          } else if (event.type === "tool_call_start") {
            setStreamingIteration(event.iteration);
            if (!event.call_id || !event.tool_name) return;
            setStreamingPhase("tool_running");
            setStreamingToolCalls((previous) => {
              const existingIndex = previous.findIndex((toolCall) =>
                matchesLiveToolCall(toolCall, event.call_key, event.call_id)
              );
              const existing = existingIndex >= 0 ? previous[existingIndex] : undefined;
              const nextToolCall: AgentLiveToolCall = {
                id: existing?.id ?? event.call_key ?? event.call_id,
                call_id: event.call_id,
                call_key: event.call_key ?? existing?.call_key,
                tool_name: event.tool_name,
                args: event.args ?? {},
                result: existing?.result ?? "",
                status: "running",
                hitl_run_id: existing?.hitl_run_id ?? null,
                error: null,
                iteration: event.iteration,
              };
              if (existingIndex >= 0) {
                return previous.map((toolCall, index) =>
                  index === existingIndex ? nextToolCall : toolCall
                );
              }
              return [
                ...previous,
                nextToolCall,
              ];
            });
          } else if (event.type === "tool_call_end") {
            setStreamingIteration(event.iteration);
            setStreamingToolCalls((previous) => {
              const existingIndex = previous.findIndex((toolCall) =>
                matchesLiveToolCall(toolCall, event.call_key, event.call_id)
              );
              if (existingIndex < 0) {
                return [
                  ...previous,
                  {
                    id: event.call_key ?? event.call_id,
                    call_id: event.call_id,
                    call_key: event.call_key,
                    tool_name: event.tool_name,
                    args: {},
                    result: event.result,
                    status: event.status,
                    hitl_run_id: event.hitl_run_id ?? null,
                    error: event.error ?? null,
                    iteration: event.iteration,
                  },
                ];
              }
              return previous.map((toolCall, index) =>
                index === existingIndex
                  ? {
                      ...toolCall,
                      call_id: event.call_id,
                      call_key: event.call_key ?? toolCall.call_key,
                      tool_name: event.tool_name,
                      result: event.result,
                      status: event.status,
                      hitl_run_id: event.hitl_run_id ?? null,
                      error: event.error ?? null,
                      iteration: event.iteration,
                    }
                  : toolCall
              );
            });
            setStreamingPhase("thinking");
          } else if (event.type === "text") {
            enqueueStreamingText(event.delta, streamGeneration);
            setStreamingPhase(null);
          } else if (event.type === "done") {
            receivedTerminalEvent = true;
            resetStreamingState();
            abortControllerRef.current = null;
            loadSessionDetail(streamSessionId);
            if (event.hitl_run_ids && event.hitl_run_ids.length > 0) {
              setHitlLinks(event.hitl_run_ids);
            }
          } else if (event.type === "error") {
            receivedTerminalEvent = true;
            resetStreamingState();
            abortControllerRef.current = null;
            setChatError(event.error || "エラーが発生しました。");
          }
        },
        controller.signal
      );
      if (isCurrentStream() && !receivedTerminalEvent) {
        resetStreamingState();
        abortControllerRef.current = null;
        setChatError("応答ストリームが完了前に終了しました。");
      }
    } catch (err: unknown) {
      if (!isCurrentStream()) return;
      const isAbort =
        (err instanceof DOMException && err.name === "AbortError") ||
        (typeof err === "object" && err !== null && "name" in err && (err as { name: string }).name === "AbortError");
      if (isAbort) {
        resetStreamingState();
        abortControllerRef.current = null;
        return;
      }
      resetStreamingState();
      abortControllerRef.current = null;
      setChatError(err instanceof Error ? err.message : "メッセージの送信に失敗しました。");
    }
  };

  return (
    <div className="flex h-full flex-col bg-slate-50 lg:flex-row">
      {/* Left Pane: Split Upper (Agent List) & Lower (Conversation History) */}
      <div className="flex w-full flex-col border-r border-slate-200 bg-white lg:w-64 shrink-0">
        {/* Upper Section: AI Agent List */}
        <div className="flex flex-1 flex-col min-h-0 border-b border-slate-200">
          <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
            <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">AIエージェント</h2>
            <button
              type="button"
              onClick={handleOpenCreateForm}
              className="rounded cursor-pointer bg-slate-900 px-2 py-1 text-[11px] text-white hover:bg-slate-800"
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
                    // Switching agents invalidates the current session; clear the URL param.
                    setSearchParams(
                      (prev) => {
                        const next = new URLSearchParams(prev);
                        next.delete("session_id");
                        return next;
                      },
                      { replace: true },
                    );
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

        {/* Lower Section: Conversation History List */}
        <div className="flex flex-1 flex-col min-h-0">
          <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
            <h3 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">会話履歴</h3>
            {selectedAgentId && (
              <button
                type="button"
                onClick={handleCreateSession}
                className="rounded cursor-pointer border border-slate-300 bg-white px-2 py-1 text-[11px] text-slate-700 hover:bg-slate-100"
              >
                ＋ 新しい会話
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {!selectedAgentId ? (
              <p className="p-3 text-center text-xs text-slate-400">
                エージェントを選択してください
              </p>
            ) : sessions.length === 0 ? (
              <p className="p-3 text-center text-xs text-slate-400">
                会話履歴がありません
              </p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.session_id}
                  className={`group flex items-center justify-between rounded-lg px-3 py-2 text-xs transition ${
                    selectedSessionId === s.session_id
                      ? "bg-slate-900 text-white font-medium"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedSessionId(s.session_id);
                      setSearchParams(
                        (prev) => {
                          const next = new URLSearchParams(prev);
                          next.set("session_id", s.session_id);
                          return next;
                        },
                        { replace: true },
                      );
                    }}
                    className="truncate text-left cursor-pointer flex-1 min-w-0 mr-1"
                  >
                    <div className="truncate font-medium">{s.title}</div>
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSessionToDelete(s);
                    }}
                    className={`text-[10px] p-0.5 rounded cursor-pointer transition ${
                      selectedSessionId === s.session_id
                        ? "text-slate-300 hover:text-white hover:bg-slate-800"
                        : "text-slate-400 hover:text-slate-700 hover:bg-slate-200"
                    }`}
                    aria-label="会話削除"
                  >
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>
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

            {/* Chat Messages View */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {messages.length === 0 && !isStreaming ? (
                <div className="flex h-full items-center justify-center text-xs text-slate-400">
                  メッセージを入力して会話を開始してください。
                </div>
              ) : (
                messages.map((m) => {
                  const relatedRun =
                    m.role === "assistant"
                      ? runsByMessageId.get(m.message_id) ?? null
                      : null;
                  const toolCalls: AgentToolCall[] = relatedRun?.tool_calls || [];
                  const isAssistant = m.role === "assistant";
                  return (
                    <div key={m.message_id} className="space-y-1">
                      {/* Tool calls (chronological: before the assistant's final response) */}
                      {toolCalls.length > 0 && (
                        <div className="flex justify-start">
                          <div className="max-w-xl w-full space-y-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                              ツール呼び出し {toolCalls.length}件
                            </div>
                            {toolCalls.map((tc) => (
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
                                          : "bg-rose-50 text-rose-700 border-rose-200"
                                      }`}
                                    >
                                      {tc.status === "succeeded" ? "成功" : "失敗"}
                                    </span>
                                    {tc.hitl_run_id && (
                                      <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 truncate">
                                        HITL: {tc.hitl_run_id}
                                      </span>
                                    )}
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
                      )}
                      {/* Message bubble (user: plain text, assistant: Markdown) */}
                      <div
                        className={`flex ${
                          m.role === "user" ? "justify-end" : "justify-start"
                        }`}
                      >
                        <div
                          className={`max-w-xl rounded-2xl px-4 py-2.5 text-xs shadow-sm ${
                            isAssistant
                              ? "bg-white border border-slate-200 text-slate-800"
                              : "bg-slate-900 text-white whitespace-pre-wrap"
                          }`}
                        >
                          {isAssistant ? (
                            <MarkdownPreview content={m.content} />
                          ) : (
                            m.content
                          )}
                        </div>
                      </div>
                      {/* Footer: copy button + timestamp */}
                      <div
                        className={`flex items-center gap-2 text-[10px] text-slate-400 ${
                          m.role === "user" ? "justify-end" : "justify-start"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => handleCopyMessage(m.content, m.message_id)}
                          className="inline-flex items-center gap-1 cursor-pointer rounded px-1.5 py-0.5 hover:bg-slate-100 hover:text-slate-600 transition"
                          aria-label="メッセージをコピー"
                          data-testid={`copy-message-${m.message_id}`}
                        >
                          {copiedMessageId === m.message_id ? (
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
                        <span aria-label="送信時刻">{formatDateTime(m.created_at)}</span>
                      </div>
                    </div>
                  );
                })
              )}

              {/* Live Streaming Response Chunk */}
              {isStreaming && (
                <div className="space-y-3">
                  {(displayedStreamingPhase || streamingToolCalls.length > 0) && (
                    <div className="flex justify-start">
                      <div className="max-w-xl w-full space-y-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                        {displayedStreamingPhase === "thinking" && streamingToolCalls.length === 0 && (
                          <div className="flex items-center gap-2 text-xs text-slate-600">
                            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                            LLMが考え中…{streamingIteration ? ` (iter ${streamingIteration})` : ""}
                          </div>
                        )}
                        {displayedStreamingPhase === "thinking" && streamingToolCalls.length > 0 && (
                          <div className="flex items-center gap-2 text-[11px] text-slate-500">
                            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                            ツール結果を踏まえて次の応答を生成中…
                          </div>
                        )}
                        {displayedStreamingPhase === "tool_preparing" && (
                          <div className="flex items-center gap-2 text-xs text-blue-700">
                            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-blue-500" />
                            ツール呼び出しを準備中…
                          </div>
                        )}
                        {displayedStreamingPhase === "tool_running" && (
                          <div className="flex items-center gap-2 text-xs text-amber-700">
                            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
                            ツールを実行中…
                          </div>
                        )}
                        {streamingToolCalls.length > 0 && (
                          <>
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
                                      className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold border ${getLiveStatusClass(tc.status)}`}
                                    >
                                      {getLiveStatusLabel(tc.status)}
                                    </span>
                                    {tc.hitl_run_id && (
                                      <span className="text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-1 truncate">
                                        HITL: {tc.hitl_run_id}
                                      </span>
                                    )}
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
                                            {(tc.result && tc.result.length > LIVE_RESULT_MAX_CHARS ? tc.result.slice(0, LIVE_RESULT_MAX_CHARS) + "\n…(truncated for live view)" : tc.result) || "-"}
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
                          </>
                        )}
                        {streamingToolCalls.length === 0 && displayedStreamingPhase === "tool_preparing" && (
                          <div className="text-[11px] text-slate-400">ツール呼び出しを準備中…</div>
                        )}
                      </div>
                    </div>
                  )}
                  <div className="flex justify-start">
                    <div className="max-w-xl rounded-2xl border border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-800 shadow-sm">
                      {streamingText ? (
                        <MarkdownPreview content={streamingText} />
                      ) : displayedStreamingPhase === "thinking" ? (
                        <span className="flex items-center gap-2 text-slate-500">
                          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
                          考え中…
                        </span>
                      ) : displayedStreamingPhase === "tool_preparing" ? (
                        <span className="text-slate-500">ツール呼び出しを準備しています…</span>
                      ) : displayedStreamingPhase === "tool_running" ? (
                        <span className="text-slate-500">ツールの実行結果を待っています…</span>
                      ) : (
                        "考え中…"
                      )}
                    </div>
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
                    : "左側の「＋ 新しい会話」をクリックして会話を開始してください"
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
