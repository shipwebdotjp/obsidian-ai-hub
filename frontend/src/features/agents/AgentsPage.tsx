import React, { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createAgent,
  createAgentSession,
  createPromptTemplate,
  deleteAgent,
  deleteAgentSession,
  deletePromptTemplate,
  getAgentSessionDetail,
  listAgents,
  listAgentSessions,
  listAgentTools,
  listPromptTemplates,
  searchAgentMessages,
  streamAgentMessage,
  updateAgent,
  updateAgentSession,
  updatePromptTemplate,
} from "../../api/client";
import type {
  Agent,
  AgentLiveToolCall,
  AgentMessage,
  AgentMessageAttachment,
  AgentMessageSearchResult,
  AgentPromptTemplate,
  AgentRun,
  AgentSession,
  AgentStreamEvent,
  AgentTool,
  AgentToolCall,
} from "../../api/types";
import { ROUTES } from "../../constants/routes";
import { useChatSendMode } from "../settings/chatSendMode";
import MarkdownPreview from "../../components/MarkdownPreview";
import { formatDateTime } from "../../utils/date";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  Image as ImageIcon,
  Pin,
  Plus,
  SendHorizontal,
  Settings,
  Trash2,
  X,
} from "lucide-react";

// keep in sync with runtime.py _LIVE_RESULT_MAX_CHARS (DB is 20000)
const LIVE_RESULT_MAX_CHARS = 2000;

const MAX_AGENT_IMAGES = 5;
const MAX_AGENT_IMAGE_BYTES = 8 * 1024 * 1024;

// Tailwind v4 default `lg` breakpoint is 1024px. Used to keep JS behavior
// (e.g. body scroll lock) in sync with the responsive drawer visibility.
const LG_BREAKPOINT = 1024;

interface PendingAttachment {
  previewUrl: string;
  name: string;
  mime_type: string;
  data: string;
  size: number;
}

export function filterCommandPaletteTemplates(
  templates: AgentPromptTemplate[],
  inputText: string,
): AgentPromptTemplate[] {
  if (!inputText.startsWith("/")) return [];
  const rawQuery = inputText.slice(1);
  const explicitMatch = rawQuery.match(/^template\s+(.*)/i);
  const query = (explicitMatch ? explicitMatch[1] : rawQuery).trim();
  const lowerQuery = query.toLowerCase();

  if (!lowerQuery) {
    return templates.slice(0, 8);
  }

  const startsWithMatches: AgentPromptTemplate[] = [];
  const includesMatches: AgentPromptTemplate[] = [];

  for (const t of templates) {
    const lowerName = t.name.toLowerCase();
    if (lowerName.startsWith(lowerQuery)) {
      startsWithMatches.push(t);
    } else if (lowerName.includes(lowerQuery)) {
      includesMatches.push(t);
    }
  }

  return [...startsWithMatches, ...includesMatches].slice(0, 8);
}

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

const SidebarIconButton = React.forwardRef<
  HTMLButtonElement,
  { label: string; onClick: () => void; children: ReactNode }
>(function SidebarIconButton({ label, onClick, children }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      className="rounded p-1 text-slate-500 hover:bg-slate-100 cursor-pointer"
      aria-label={label}
    >
      {children}
    </button>
  );
});

function getPinButtonClass(pinned: boolean, active: boolean): string {
  if (pinned) return "text-amber-500";
  if (active) return "text-slate-300 hover:text-white hover:bg-slate-800";
  return "text-slate-400 hover:text-slate-700 hover:bg-slate-200";
}

function PinButton({
  pinned,
  active,
  onToggle,
  label,
}: {
  pinned: boolean;
  active: boolean;
  onToggle: (e: React.MouseEvent) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`inline-flex h-6 w-6 shrink-0 items-center justify-center rounded cursor-pointer transition ${getPinButtonClass(pinned, active)}`}
      aria-label={label}
      aria-pressed={pinned}
    >
      <Pin className={`h-3.5 w-3.5 ${pinned ? "fill-amber-400 text-amber-500" : ""}`} />
    </button>
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
  const [loadedSessionId, setLoadedSessionId] = useState<string | null>(null);
  const [sessionSearchQuery, setSessionSearchQuery] = useState("");
  const [sessionSearchResults, setSessionSearchResults] = useState<AgentMessageSearchResult[]>([]);
  const [isSessionSearchLoading, setIsSessionSearchLoading] = useState(false);
  const [sessionSearchError, setSessionSearchError] = useState<string | null>(null);

  // Agent form state
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [formName, setFormName] = useState("");
  const [formPrompt, setFormPrompt] = useState("");
  const [formProvider, setFormProvider] = useState("");
  const [formModel, setFormModel] = useState("");
  const [formToolIds, setFormToolIds] = useState<string[]>([]);
  const [formMaxTokens, setFormMaxTokens] = useState<string>("");
  const [formReasoningEffort, setFormReasoningEffort] = useState<string>("");
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Prompt template state (per-agent)
  const [promptTemplates, setPromptTemplates] = useState<AgentPromptTemplate[]>([]);
  const [templateSelectorOpen, setTemplateSelectorOpen] = useState(false);
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [templateFormName, setTemplateFormName] = useState("");
  const [templateFormContent, setTemplateFormContent] = useState("");
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);

  // Chat stream state
  const [inputText, setInputText] = useState("");
  const [chatSendMode] = useChatSendMode();
  const chatInputRef = useRef<HTMLTextAreaElement>(null);
  const [isCommandPaletteDismissed, setIsCommandPaletteDismissed] = useState(false);
  const [paletteSelectedIndex, setPaletteSelectedIndex] = useState(0);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamingToolCalls, setStreamingToolCalls] = useState<AgentLiveToolCall[]>([]);
  const [streamingPhase, setStreamingPhase] = useState<"thinking" | "tool_preparing" | "tool_running" | null>(null);
  const [streamingIteration, setStreamingIteration] = useState<number | null>(null);
  const [hitlLinks, setHitlLinks] = useState<string[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const copyResetRef = useRef<number | null>(null);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentReadsPending, setAttachmentReadsPending] = useState(0);
  const [isDragOver, setIsDragOver] = useState(false);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const plusMenuRef = useRef<HTMLDivElement | null>(null);

  // Modal delete targets
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);
  const [sessionToDelete, setSessionToDelete] = useState<AgentSession | null>(null);

  // Mobile / desktop pane layout state.
  // `leftPaneOpen` controls the mobile-only overlay drawer; on desktop the
  // sidebar is rendered independently and these handlers are harmless no-ops.
  const [leftPaneOpen, setLeftPaneOpen] = useState(false);
  const [leftPaneCollapsed, setLeftPaneCollapsed] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const mobileDrawerCloseRef = useRef<HTMLButtonElement>(null);
  const mobileDrawerRef = useRef<HTMLDivElement>(null);
  const mobileDrawerTriggerRef = useRef<HTMLButtonElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const streamGenerationRef = useRef(0);
  const streamingTextBufferRef = useRef("");
  const streamingTextFrameRef = useRef<number | null>(null);
  const messageElementRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingSearchTargetRef = useRef<{ sessionId: string; messageId: string } | null>(null);

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
      setLoadedSessionId(null);
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

  const loadSessionDetail = async (sessionId: string) => {
    setActionError(null);
    try {
      const detail = await getAgentSessionDetail(sessionId);
      setMessages(detail.messages);
      setRuns(detail.runs || []);
      setLoadedSessionId(sessionId);
      setChatError(null);
    } catch (e: unknown) {
      const message =
        e instanceof Error ? e.message : "セッション詳細の読み込みに失敗しました。";
      setChatError(message);
    }
  };

  // Draft persistence helpers
  const getDraftKey = useCallback((sessionId: string) => `agent-draft:${sessionId}`, []);

  const loadDraft = useCallback(
    (sessionId: string) => {
      try {
        const raw = localStorage.getItem(getDraftKey(sessionId));
        if (!raw) {
          setInputText("");
          setPendingAttachments([]);
          return;
        }
        const draft = JSON.parse(raw) as {
          text?: string;
          attachments?: Array<Omit<PendingAttachment, "previewUrl">>;
          savedAt?: string;
        };
        setInputText(draft.text || "");
        const validAttachments = (draft.attachments ?? []).filter(
          (att): att is { name: string; mime_type: string; data: string; size: number } =>
            Boolean(att && att.mime_type && att.data)
        );
        if (validAttachments.length > 0) {
          setPendingAttachments(
            validAttachments.map((att) => ({
              ...att,
              previewUrl: `data:${att.mime_type};base64,${att.data}`,
            }))
          );
        } else {
          setPendingAttachments([]);
        }
      } catch {
        // Corrupt or unreadable draft: start fresh.
        setInputText("");
        setPendingAttachments([]);
      }
    },
    [getDraftKey]
  );

  const clearDraft = useCallback(
    (sessionId: string) => {
      try {
        localStorage.removeItem(getDraftKey(sessionId));
      } catch {
        // ignore
      }
    },
    [getDraftKey]
  );

  const DRAFT_SIZE_LIMIT = 4_000_000; // ~4MB to stay under typical localStorage quotas.

  const saveDraft = useCallback(
    (sessionId: string, text: string, attachments: PendingAttachment[]) => {
      try {
        const draft = {
          text,
          attachments: attachments.map((att) => ({
            name: att.name,
            mime_type: att.mime_type,
            data: att.data,
            size: att.size,
          })),
          savedAt: new Date().toISOString(),
        };
        const serialized = JSON.stringify(draft);
        if (serialized.length > DRAFT_SIZE_LIMIT) {
          // Drop the draft rather than silently failing on quota.
          clearDraft(sessionId);
          setChatError("下書きが大きすぎて保存できません（画像を減らしてください）。");
          return;
        }
        localStorage.setItem(getDraftKey(sessionId), serialized);
      } catch (e) {
        // QuotaExceeded or private mode: don't block typing.
        console.error("Failed to save draft:", e);
      }
    },
    [getDraftKey, clearDraft]
  );

  // Load session detail messages when session changes
  useEffect(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    resetStreamingState();

    if (!selectedSessionId) {
      setMessages([]);
      setLoadedSessionId(null);
      setInputText("");
      setPendingAttachments([]);
      if (imageInputRef.current) {
        imageInputRef.current.value = "";
      }
      return;
    }
    setLoadedSessionId(null);
    loadSessionDetail(selectedSessionId);
    setHitlLinks([]);
    loadDraft(selectedSessionId);
    if (imageInputRef.current) {
      imageInputRef.current.value = "";
    }
  }, [selectedSessionId, loadDraft]);

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
    if (messageElement) {
      messageElement.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    pendingSearchTargetRef.current = null;
  }, [loadedSessionId, messages]);

  // Auto-save draft (text + attachments) with a 200ms debounce.
  useEffect(() => {
    if (!selectedSessionId) return;
    const hasContent = inputText.trim().length > 0 || pendingAttachments.length > 0;
    if (!hasContent) {
      clearDraft(selectedSessionId);
      return;
    }
    const timer = window.setTimeout(() => {
      saveDraft(selectedSessionId, inputText, pendingAttachments);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [inputText, pendingAttachments, selectedSessionId, saveDraft, clearDraft]);

  // Close the plus menu and template selector when clicking outside of them.
  useEffect(() => {
    if (!plusMenuOpen && !templateSelectorOpen) return;
    const onClick = (e: MouseEvent) => {
      if (!(e.target instanceof Node)) return;
      if (plusMenuRef.current && !plusMenuRef.current.contains(e.target)) {
        setPlusMenuOpen(false);
        setTemplateSelectorOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [plusMenuOpen, templateSelectorOpen]);

  // Modal / drawer ESC listener
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAgentToDelete(null);
        setSessionToDelete(null);
        setLeftPaneOpen(false);
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

  const loadPromptTemplates = useCallback(async (agentId: string) => {
    setTemplateLoading(true);
    try {
      const res = await listPromptTemplates(agentId);
      setPromptTemplates(res.templates);
    } catch {
      // Templates are optional; keep previous state on error.
    } finally {
      setTemplateLoading(false);
    }
  }, []);

  const handleSelectTemplate = (content: string) => {
    setInputText(content);
    setTemplateSelectorOpen(false);
    setPlusMenuOpen(false);
    setIsCommandPaletteDismissed(false);
    setTimeout(() => {
      chatInputRef.current?.focus();
    }, 0);
  };

  useEffect(() => {
    if (!inputText.startsWith("/")) {
      setIsCommandPaletteDismissed(false);
    }
    setPaletteSelectedIndex(0);
  }, [inputText]);

  const isPaletteActive =
    Boolean(activeAgent) &&
    Boolean(selectedSessionId) &&
    !isStreaming &&
    inputText.startsWith("/") &&
    !isCommandPaletteDismissed;

  const paletteCandidates = useMemo(
    () => (isPaletteActive ? filterCommandPaletteTemplates(promptTemplates, inputText) : []),
    [isPaletteActive, promptTemplates, inputText],
  );

  // Load templates for active chat agent (when not editing/creating)
  useEffect(() => {
    if (!activeAgent || isCreatingAgent || isEditingAgent) return;
    void loadPromptTemplates(activeAgent.agent_id);
  }, [activeAgent?.agent_id, isCreatingAgent, isEditingAgent, loadPromptTemplates]);

  const handleCreateOrUpdateTemplate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAgentId) return;
    setTemplateError(null);
    try {
      if (editingTemplateId) {
        const res = await updatePromptTemplate(editingTemplateId, {
          name: templateFormName,
          content: templateFormContent,
        });
        setPromptTemplates((prev) => prev.map((t) => (t.template_id === editingTemplateId ? res.template : t)));
        setEditingTemplateId(null);
      } else {
        const res = await createPromptTemplate(selectedAgentId, {
          name: templateFormName,
          content: templateFormContent,
        });
        setPromptTemplates((prev) => [...prev, res.template]);
      }
      setTemplateFormName("");
      setTemplateFormContent("");
    } catch (err: any) {
      setTemplateError(err.message || "テンプレートの保存に失敗しました。");
    }
  };

  const handleDeleteTemplate = async (templateId: string) => {
    setTemplateError(null);
    try {
      await deletePromptTemplate(templateId);
      setPromptTemplates((prev) => prev.filter((t) => t.template_id !== templateId));
      if (editingTemplateId === templateId) {
        setEditingTemplateId(null);
        setTemplateFormName("");
        setTemplateFormContent("");
      }
    } catch (err: any) {
      setTemplateError(err.message || "テンプレートの削除に失敗しました。");
    }
  };

  const handleEditTemplate = (t: AgentPromptTemplate) => {
    setEditingTemplateId(t.template_id);
    setTemplateFormName(t.name);
    setTemplateFormContent(t.content);
    setTemplateError(null);
  };

  // Agent Form Actions
  const handleOpenCreateForm = () => {
    setIsCreatingAgent(true);
    setIsEditingAgent(false);
    setFormName("");
    setFormPrompt("");
    setFormProvider("");
    setFormModel("");
    setFormToolIds([]);
    setFormMaxTokens("");
    setFormReasoningEffort("");
    setIsAdvancedOpen(false);
    setFormError(null);
    setActionError(null);
    setPromptTemplates([]);
    setTemplateFormName("");
    setTemplateFormContent("");
    setEditingTemplateId(null);
    setTemplateError(null);
  };

  const handleOpenEditForm = (agent: Agent) => {
    setIsEditingAgent(true);
    setIsCreatingAgent(false);
    setFormName(agent.name);
    setFormPrompt(agent.system_prompt);
    setFormProvider(agent.provider || "");
    setFormModel(agent.model || "");
    setFormToolIds(agent.tool_ids || []);
    const adv = agent.advanced_params ?? {};
    setFormMaxTokens(adv.max_tokens != null ? String(adv.max_tokens) : "");
    setFormReasoningEffort(adv.reasoning?.effort ?? "");
    setIsAdvancedOpen(Boolean(adv.max_tokens != null || adv.reasoning?.effort));
    setFormError(null);
    setActionError(null);
    setTemplateFormName("");
    setTemplateFormContent("");
    setEditingTemplateId(null);
    setTemplateError(null);
    // Load templates for this agent
    void loadPromptTemplates(agent.agent_id);
  };

  const buildAdvancedParams = (): { max_tokens?: number; reasoning?: { effort?: string } } => {
    const params: { max_tokens?: number; reasoning?: { effort?: string } } = {};
    const mt = formMaxTokens.trim();
    if (mt !== "") {
      const n = Number(mt);
      if (!Number.isNaN(n) && n > 0) params.max_tokens = Math.trunc(n);
    }
    const re = formReasoningEffort.trim();
    if (re !== "") {
      params.reasoning = { effort: re };
    }
    return params;
  };

  const handleSaveAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setActionError(null);
    const advanced_params = buildAdvancedParams();
    try {
      if (isCreatingAgent) {
        const res = await createAgent({
          name: formName,
          system_prompt: formPrompt,
          provider: formProvider || undefined,
          model: formModel || undefined,
          tool_ids: formToolIds,
          advanced_params: Object.keys(advanced_params).length ? advanced_params : undefined,
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
          advanced_params,
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

  const handleToggleAgentPin = async (agent: Agent, e: React.MouseEvent) => {
    e.stopPropagation();
    setActionError(null);
    try {
      await updateAgent(agent.agent_id, { pinned: !agent.pinned_at });
      const res = await listAgents();
      setAgents(res.agents);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "ピン留めの更新に失敗しました。";
      setActionError(message);
    }
  };

  const handleToggleSessionPin = async (session: AgentSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setActionError(null);
    try {
      await updateAgentSession(session.session_id, { pinned: !session.pinned_at });
      if (selectedAgentId) {
        const res = await listAgentSessions(selectedAgentId);
        setSessions(res.sessions);
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "ピン留めの更新に失敗しました。";
      setActionError(message);
    }
  };

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
        setChatError(`画像ファイル以外は添付できません: ${file.name || "ファイル"}`);
        return;
      }
      if (file.size > MAX_AGENT_IMAGE_BYTES) {
        setChatError(
          `${file.name || "ファイル"} はサイズ上限(${Math.floor(MAX_AGENT_IMAGE_BYTES / (1024 * 1024))}MB)を超えています。`
        );
        return;
      }
      accepted.push(file);
    }
    setPendingAttachments((prev) => {
      const remainingSlots = MAX_AGENT_IMAGES - prev.length;
      if (remainingSlots <= 0) {
        setChatError(`画像は最大${MAX_AGENT_IMAGES}枚まで添付できます。`);
        return prev;
      }
      const limited = accepted.slice(0, remainingSlots);
      if (accepted.length > limited.length) {
        setChatError(
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
            setChatError(`画像の読み込みに失敗しました: ${file.name || "ファイル"}`);
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
      return prev;
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
    e.preventDefault();
    void handleFilesSelected(files);
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

  const handleSelectSearchResult = (result: AgentMessageSearchResult) => {
    const isCurrentSession =
      selectedSessionId === result.session_id && loadedSessionId === result.session_id;
    if (isCurrentSession) {
      setLeftPaneOpen(false);
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
    setSelectedAgentId(result.agent_id);
    setSelectedSessionId(result.session_id);
    setLeftPaneOpen(false);
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

  // Move focus into the mobile drawer when it opens and restore it to the
  // trigger button when the drawer closes. Also trap Tab focus inside the drawer.
  useEffect(() => {
    if (leftPaneOpen) {
      mobileDrawerCloseRef.current?.focus();

      const drawer = mobileDrawerRef.current;
      if (!drawer) return;

      const focusableSelector =
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      const onKeyDown = (e: KeyboardEvent) => {
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
      drawer.addEventListener("keydown", onKeyDown);
      return () => {
        drawer.removeEventListener("keydown", onKeyDown);
        mobileDrawerTriggerRef.current?.focus();
      };
    }
  }, [leftPaneOpen]);

  // Lock body scroll only while the mobile sidebar drawer is actually visible.
  useEffect(() => {
    if (!leftPaneOpen) return;
    // Tailwind `lg` breakpoint is min-width: 1024px, so the drawer is only
    // shown below that width. Keep scroll-lock in sync with that breakpoint.
    if (typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(`(max-width: ${LG_BREAKPOINT - 1}px)`);
    if (!mql.matches) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onChange = (e: MediaQueryListEvent) => {
      document.body.style.overflow = e.matches ? "hidden" : original;
    };
    if (typeof mql.addEventListener === "function") {
      mql.addEventListener("change", onChange);
      return () => {
        mql.removeEventListener("change", onChange);
        document.body.style.overflow = original;
      };
    }
    return () => {
      document.body.style.overflow = original;
    };
  }, [leftPaneOpen]);

  // Send Message & Stream Response
  const submitMessage = async () => {
    if (!selectedSessionId || (!inputText.trim() && pendingAttachments.length === 0) || isStreaming) return;

    const streamSessionId = selectedSessionId;
    const userText = inputText.trim();
    const attachmentsSnapshot = pendingAttachments.map<AgentMessageAttachment>((att) => ({
      name: att.name,
      mime_type: att.mime_type,
      data: att.data,
    }));
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    invalidatePendingStreamingText();
    const streamGeneration = streamGenerationRef.current;
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setInputText("");
    setPendingAttachments([]);
    clearDraft(streamSessionId);
    if (imageInputRef.current) {
      imageInputRef.current.value = "";
    }
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
      attachments: attachmentsSnapshot.length > 0 ? attachmentsSnapshot : undefined,
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
        controller.signal,
        attachmentsSnapshot.length > 0 ? attachmentsSnapshot : undefined
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

  const handleSendMessage = (e: React.FormEvent) => {
    e.preventDefault();
    void submitMessage();
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;

    if (isPaletteActive) {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void submitMessage();
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (
          paletteCandidates.length > 0 &&
          paletteSelectedIndex >= 0 &&
          paletteSelectedIndex < paletteCandidates.length
        ) {
          handleSelectTemplate(paletteCandidates[paletteSelectedIndex].content);
        }
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (paletteCandidates.length > 0) {
          setPaletteSelectedIndex((prev) => (prev + 1) % paletteCandidates.length);
        }
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        if (paletteCandidates.length > 0) {
          setPaletteSelectedIndex(
            (prev) => (prev - 1 + paletteCandidates.length) % paletteCandidates.length,
          );
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setIsCommandPaletteDismissed(true);
        return;
      }
    }

    if (chatSendMode === "enter") {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void submitMessage();
      }
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void submitMessage();
    }
  };

  useEffect(() => {
    const el = chatInputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [inputText]);

  const inputPlaceholder = !selectedSessionId
    ? "左側の「＋ 新しい会話」をクリックして会話を開始してください"
    : chatSendMode === "enter"
      ? "メッセージを入力…（Enterで送信 / Shift+Enterで改行）"
      : "メッセージを入力…（Enterで改行 / Ctrl+Enterで送信）";

  const sidebarContent = (
    <>

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
                <div
                  key={agent.agent_id}
                  className={`group flex items-center justify-between rounded-lg px-3 py-2 text-xs transition ${
                    selectedAgentId === agent.agent_id &&
                    !isCreatingAgent &&
                    !isEditingAgent
                      ? "bg-slate-900 text-white font-medium"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedAgentId(agent.agent_id);
                      setIsCreatingAgent(false);
                      setIsEditingAgent(false);
                      setLeftPaneOpen(false);
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
                    className="flex-1 text-left cursor-pointer min-w-0"
                  >
                    <div className="truncate font-semibold">{agent.name}</div>
                    <div className="truncate text-[10px] opacity-75">
                      {agent.tool_ids.length} ツール | {agent.provider || "既定"}
                    </div>
                  </button>
                  <PinButton
                    pinned={!!agent.pinned_at}
                    active={selectedAgentId === agent.agent_id && !isCreatingAgent && !isEditingAgent}
                    onToggle={(e) => handleToggleAgentPin(agent, e)}
                    label={agent.pinned_at ? "ピン留めを解除" : "ピン留めする"}
                  />
                </div>
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
          <div className="border-b border-slate-200 p-2">
            <input
              type="search"
              value={sessionSearchQuery}
              onChange={(e) => setSessionSearchQuery(e.target.value)}
              placeholder="すべての会話を検索"
              aria-label="会話履歴を検索"
              className="w-full rounded border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 placeholder:text-slate-400 focus:border-slate-500 focus:outline-none"
            />
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {sessionSearchQuery.trim() ? (
              isSessionSearchLoading ? (
                <p className="p-3 text-center text-xs text-slate-400">検索中…</p>
              ) : sessionSearchError ? (
                <p className="p-3 text-center text-xs text-rose-600">{sessionSearchError}</p>
              ) : sessionSearchResults.length === 0 ? (
                <p className="p-3 text-center text-xs text-slate-400">該当するメッセージはありません</p>
              ) : (
                sessionSearchResults.map((result) => (
                  <button
                    key={result.message_id}
                    type="button"
                    onClick={() => handleSelectSearchResult(result)}
                    data-testid={`agent-message-search-result-${result.message_id}`}
                    className="w-full rounded px-3 py-2 text-left text-xs text-slate-700 transition hover:bg-slate-100 cursor-pointer"
                  >
                    <div className="flex items-center gap-1 truncate text-[10px] text-slate-500">
                      <span className="font-semibold text-slate-700">{result.agent_name}</span>
                      <span aria-hidden="true">/</span>
                      <span className="truncate">{result.session_title}</span>
                    </div>
                    <div className="mt-0.5 line-clamp-2 break-words text-slate-800">
                      <span className="mr-1 text-[10px] text-slate-500">
                        {result.role === "user" ? "ユーザー:" : "アシスタント:"}
                      </span>
                      {result.snippet}
                    </div>
                  </button>
                ))
              )
            ) : !selectedAgentId ? (
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
                        setLeftPaneOpen(false);
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
                  <PinButton
                    pinned={!!s.pinned_at}
                    active={selectedSessionId === s.session_id}
                    onToggle={(e) => handleToggleSessionPin(s, e)}
                    label={s.pinned_at ? "ピン留めを解除" : "ピン留めする"}
                  />
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
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
    </>
  );

  return (
    <div className="flex h-full flex-col bg-slate-50 lg:flex-row">
      {/* Mobile overlay drawer */}
      {leftPaneOpen && (
        <div
          ref={mobileDrawerRef}
          className="fixed inset-0 z-50 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="エージェントと会話"
        >
          <div className="flex h-full w-64 flex-col border-r border-slate-200 bg-white">
            <div className="flex items-center justify-end border-b border-slate-200 p-2">
              <SidebarIconButton
                ref={mobileDrawerCloseRef}
                label="サイドバーを閉じる"
                onClick={() => setLeftPaneOpen(false)}
              >
                <X className="h-4 w-4" />
              </SidebarIconButton>
            </div>
            {sidebarContent}
          </div>
          <button
            type="button"
            aria-label="オーバーレイを閉じる"
            onClick={() => setLeftPaneOpen(false)}
            className="min-w-0 flex-1 bg-slate-900/40"
          />
        </div>
      )}

      {/* Desktop collapsible left pane */}
      {!leftPaneCollapsed && (
        <div className="hidden h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
          <div className="flex items-center justify-end border-b border-slate-200 p-2">
            <SidebarIconButton
              label="サイドバーを畳む"
              onClick={() => setLeftPaneCollapsed(true)}
            >
              <ChevronLeft className="h-4 w-4" />
            </SidebarIconButton>
          </div>
          {sidebarContent}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {isCreatingAgent || isEditingAgent ? (
          /* Agent Create / Edit Form */
          <div className="flex-1 overflow-y-auto p-6">
            <div className="mx-auto max-w-2xl rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  {isEditingAgent && activeAgent && (
                    <button
                      type="button"
                      onClick={() => setAgentToDelete(activeAgent)}
                      className="inline-flex h-7 w-7 items-center justify-center rounded text-rose-600 hover:bg-rose-50 cursor-pointer"
                      aria-label="エージェントを削除"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                  <h3 className="text-base font-semibold text-slate-900">
                    {isCreatingAgent
                      ? "新規エージェント作成"
                      : "エージェント設定編集"}
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setIsCreatingAgent(false);
                    setIsEditingAgent(false);
                  }}
                  className="inline-flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 cursor-pointer"
                  aria-label="閉じる"
                >
                  <X className="h-4 w-4" />
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

                <details
                  open={isAdvancedOpen}
                  onToggle={(e) => setIsAdvancedOpen((e.target as HTMLDetailsElement).open)}
                  className="rounded-md border border-slate-200 bg-slate-50/50"
                >
                  <summary className="cursor-pointer list-none flex items-center justify-between px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50">
                    <span>高度なパラメーター</span>
                    <span className="text-[10px] text-slate-400">{isAdvancedOpen ? "▲" : "▼"}</span>
                  </summary>
                  <div className="border-t border-slate-200 bg-white p-3 space-y-3">
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">
                        最大トークン数 (max_tokens / max_output_tokens)
                      </label>
                      <input
                        type="number"
                        value={formMaxTokens}
                        onChange={(e) => setFormMaxTokens(e.target.value)}
                        placeholder="例: 4096 (空欄で既定値)"
                        className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                      />
                      <p className="mt-1 text-[10px] text-slate-500">
                        OpenAI は Responses API では max_output_tokens、Chat Completions では max_completion_tokens へ、Ollama では num_predict へ自動マッピングされます。
                      </p>
                    </div>
                    <div>
                      <label className="block font-medium text-slate-700 mb-1">
                        reasoning.effort
                      </label>
                      <input
                        type="text"
                        value={formReasoningEffort}
                        onChange={(e) => setFormReasoningEffort(e.target.value)}
                        placeholder="例: low / medium / high (空欄で既定値)"
                        className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                      />
                      <p className="mt-1 text-[10px] text-slate-500">
                        OpenAI/opencode_go では reasoning_effort、Ollama では reasoning へマッピングされます。
                      </p>
                    </div>
                  </div>
                </details>

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
              {isEditingAgent && selectedAgentId && (
                <div className="mt-4 rounded-md border border-slate-200 bg-white p-3 space-y-3">
                  <div className="flex items-center justify-between">
                    <label className="block font-medium text-slate-700">
                      プロンプトテンプレート
                    </label>
                    <span className="text-[10px] text-slate-500">
                      {templateLoading ? "読込中…" : `${promptTemplates.length}件`}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-500">
                    エージェントごとに登録した定型プロンプト。チャット入力欄で呼び出して置き換えます。
                  </p>
                  {templateError && (
                    <div className="rounded bg-red-50 p-2 text-[11px] text-red-600">{templateError}</div>
                  )}
                  {promptTemplates.length > 0 && (
                    <div className="space-y-1 max-h-48 overflow-y-auto border border-slate-100 rounded p-2">
                      {promptTemplates.map((t) => (
                        <div
                          key={t.template_id}
                          className={`flex items-start justify-between gap-2 rounded p-2 text-xs ${editingTemplateId === t.template_id ? "bg-indigo-50 border border-indigo-200" : "bg-slate-50 border border-slate-200"}`}
                        >
                          <div className="min-w-0 flex-1">
                            <div className="font-semibold truncate text-slate-800">{t.name}</div>
                            <div className="text-[11px] text-slate-600 whitespace-pre-wrap break-words line-clamp-2">{t.content}</div>
                          </div>
                          <div className="flex shrink-0 gap-1">
                            <button
                              type="button"
                              onClick={() => handleEditTemplate(t)}
                              className="rounded cursor-pointer bg-white border border-slate-300 px-2 py-1 text-[10px] hover:bg-slate-50"
                            >
                              編集
                            </button>
                            <button
                              type="button"
                              onClick={() => handleDeleteTemplate(t.template_id)}
                              className="rounded cursor-pointer bg-white border border-red-200 px-2 py-1 text-[10px] text-red-600 hover:bg-red-50"
                            >
                              削除
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  <form onSubmit={handleCreateOrUpdateTemplate} className="space-y-2 border-t border-slate-100 pt-3">
                    <div className="text-[11px] font-medium text-slate-700">
                      {editingTemplateId ? "テンプレートを編集" : "テンプレートを追加"}
                    </div>
                    <input
                      type="text"
                      value={templateFormName}
                      onChange={(e) => setTemplateFormName(e.target.value)}
                      placeholder="テンプレート名"
                      className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                      required
                    />
                    <textarea
                      rows={3}
                      value={templateFormContent}
                      onChange={(e) => setTemplateFormContent(e.target.value)}
                      placeholder="テンプレート本文"
                      className="w-full rounded-md border border-slate-300 p-2 text-xs focus:border-slate-500 focus:outline-none"
                      required
                    />
                    <div className="flex gap-2">
                      <button
                        type="submit"
                        className="rounded cursor-pointer bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800"
                      >
                        {editingTemplateId ? "更新" : "追加"}
                      </button>
                      {editingTemplateId && (
                        <button
                          type="button"
                          onClick={() => {
                            setEditingTemplateId(null);
                            setTemplateFormName("");
                            setTemplateFormContent("");
                            setTemplateError(null);
                          }}
                          className="rounded cursor-pointer border border-slate-300 bg-white px-3 py-1.5 text-xs hover:bg-slate-50"
                        >
                          キャンセル
                        </button>
                      )}
                    </div>
                  </form>
                </div>
              )}
            </div>
          </div>
        ) : activeAgent ? (
          /* Active Agent Workspace */
          <div className="flex flex-1 flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center gap-2 min-w-0">
                <button
                  ref={mobileDrawerTriggerRef}
                  type="button"
                  onClick={() => setLeftPaneOpen(true)}
                  className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
                  aria-label="エージェントと会話を選択"
                >
                  エージェント / 会話
                </button>
                {leftPaneCollapsed && (
                  <button
                    type="button"
                    onClick={() => setLeftPaneCollapsed(false)}
                    className="hidden h-8 w-8 items-center justify-center rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 cursor-pointer lg:inline-flex"
                    aria-label="サイドバーを展開"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                )}
                <div className="min-w-0">
                  <h3 className="text-sm font-semibold text-slate-900">
                    {activeAgent.name}
                  </h3>
                  <p className="text-[11px] text-slate-500 truncate max-w-lg">
                    {activeAgent.system_prompt}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleOpenEditForm(activeAgent)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 cursor-pointer"
                  aria-label="設定編集"
                >
                  <Settings className="h-4 w-4" />
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
                    <div
                      key={m.message_id}
                      ref={(element) => {
                        if (element) {
                          messageElementRefs.current.set(m.message_id, element);
                        } else {
                          messageElementRefs.current.delete(m.message_id);
                        }
                      }}
                      data-message-id={m.message_id}
                      className="space-y-1"
                    >
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
                            <div className="space-y-2">
                              {m.attachments && m.attachments.length > 0 && (
                                <div className="flex flex-wrap gap-1.5">
                                  {m.attachments.map((att, attIndex) => (
                                    <img
                                      key={`${att.name}-${attIndex}`}
                                      src={`data:${att.mime_type};base64,${att.data}`}
                                      alt={att.name}
                                      className="max-h-40 max-w-[12rem] rounded border border-slate-700 object-cover"
                                    />
                                  ))}
                                </div>
                              )}
                              {m.content && <div>{m.content}</div>}
                            </div>
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
              onDragEnter={handleFormDragOver}
              onDragOver={handleFormDragOver}
              onDragLeave={handleFormDragLeave}
              onDrop={handleFormDrop}
              className="border-t border-slate-200 bg-white p-3 flex flex-col gap-2 relative"
            >
              {isDragOver && (
                <div
                  className="absolute inset-1 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-blue-600 bg-blue-600/10 pointer-events-none"
                  data-testid="agent-drop-overlay"
                >
                  <span className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white">
                    ここに画像をドロップ
                  </span>
                </div>
              )}
              {pendingAttachments.length > 0 && (
                <div className="flex flex-wrap gap-2 border border-slate-200 rounded-lg p-2 bg-slate-50/50" aria-label="送信前の添付画像">
                  {pendingAttachments.map((att, index) => (
                    <div
                      key={`${att.name}-${index}`}
                      className="relative h-16 w-16 rounded border border-slate-300 overflow-hidden bg-white"
                    >
                      <img
                        src={att.previewUrl}
                        alt={att.name}
                        className="h-full w-full object-cover"
                      />
                      <button
                        type="button"
                        onClick={() => handleRemoveAttachment(index)}
                        className="absolute top-0 right-0 inline-flex h-4 w-4 items-center justify-center rounded-bl bg-slate-900/80 text-[10px] text-white hover:bg-slate-900 cursor-pointer"
                        aria-label={`${att.name} を取り除く`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              {/* Command Palette directly above textarea */}
              {isPaletteActive && (
                <div
                  data-testid="agent-command-palette"
                  className="absolute bottom-full left-3 right-3 mb-2 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg z-20"
                >
                  {paletteCandidates.length === 0 ? (
                    <div className="p-3 text-center text-xs text-slate-400">
                      該当するテンプレートがありません
                    </div>
                  ) : (
                    paletteCandidates.map((t, index) => (
                      <button
                        key={t.template_id}
                        type="button"
                        onClick={() => handleSelectTemplate(t.content)}
                        onMouseEnter={() => setPaletteSelectedIndex(index)}
                        className={`w-full text-left px-3 py-2 text-xs border-b border-slate-50 last:border-0 cursor-pointer ${
                          index === paletteSelectedIndex ? "bg-slate-100 font-medium" : "hover:bg-slate-50"
                        }`}
                      >
                        <div className="font-medium text-slate-800 truncate">{t.name}</div>
                        <div className="text-[11px] text-slate-500 line-clamp-2 whitespace-pre-wrap break-words">
                          {t.content.length > 80 ? t.content.slice(0, 80) + "…" : t.content}
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}
              {/* Row 1: textarea */}
              <textarea
                ref={chatInputRef}
                rows={1}
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleInputKeyDown}
                onPaste={handleInputPaste}
                disabled={isStreaming || !selectedSessionId}
                placeholder={inputPlaceholder}
                className="w-full resize-none rounded-lg border border-slate-300 p-2 text-xs leading-relaxed focus:border-slate-500 focus:outline-none disabled:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
              />
              {/* Row 2: tools + model + send */}
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div ref={plusMenuRef} className="relative">
                    <button
                      type="button"
                      disabled={!activeAgent || !selectedSessionId || isStreaming}
                      onClick={() => {
                        setPlusMenuOpen((v) => !v);
                        setTemplateSelectorOpen(false);
                      }}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                      aria-label="追加メニュー"
                    >
                      <Plus className="h-4 w-4" />
                    </button>
                    {plusMenuOpen && (
                      <div className="absolute bottom-full left-0 mb-2 w-48 rounded-lg border border-slate-200 bg-white shadow-lg z-10 overflow-hidden">
                        <button
                          type="button"
                          disabled={promptTemplates.length === 0}
                          onClick={() => {
                            setTemplateSelectorOpen(true);
                            setPlusMenuOpen(false);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <FileText className="h-3.5 w-3.5 text-slate-500" />
                          テンプレート
                        </button>
                        <button
                          type="button"
                          disabled={
                            !activeAgent ||
                            !selectedSessionId ||
                            isStreaming ||
                            attachmentReadsPending > 0 ||
                            pendingAttachments.length >= MAX_AGENT_IMAGES
                          }
                          onClick={() => {
                            imageInputRef.current?.click();
                            setPlusMenuOpen(false);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <ImageIcon className="h-3.5 w-3.5 text-slate-500" />
                          {attachmentReadsPending > 0 ? "読込中…" : "画像アップロード"}
                        </button>
                      </div>
                    )}
                    {templateSelectorOpen && promptTemplates.length > 0 && (
                      <div
                        data-testid="agent-template-selector"
                        className="absolute bottom-full left-0 mb-2 w-72 max-h-64 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg z-10"
                      >
                        <div className="p-2 border-b border-slate-100 text-[11px] font-medium text-slate-500">
                          登録済みテンプレート（選択で入力を置き換え）
                        </div>
                        {promptTemplates.map((t) => (
                          <button
                            key={t.template_id}
                            type="button"
                            onClick={() => handleSelectTemplate(t.content)}
                            className="w-full text-left px-3 py-2 text-xs hover:bg-slate-50 border-b border-slate-50 last:border-0"
                          >
                            <div className="font-medium text-slate-800 truncate">{t.name}</div>
                            <div className="text-[11px] text-slate-500 line-clamp-2 whitespace-pre-wrap break-words">
                              {t.content.length > 80 ? t.content.slice(0, 80) + "…" : t.content}
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                    <input
                      ref={imageInputRef}
                      type="file"
                      accept="image/*"
                      multiple
                      data-testid="agent-image-input"
                      className="hidden"
                      onChange={(e) => {
                        void handleFilesSelected(e.target.files);
                      }}
                    />
                  </div>
                  {activeAgent && (
                    <span className="text-[11px] text-slate-400 truncate max-w-[12rem]">
                      {activeAgent.model || activeAgent.provider || "既定"}
                    </span>
                  )}
                </div>
                <button
                  type="submit"
                  disabled={
                    isStreaming ||
                    attachmentReadsPending > 0 ||
                    (!inputText.trim() && pendingAttachments.length === 0) ||
                    !selectedSessionId
                  }
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  aria-label="送信"
                >
                  <SendHorizontal className="h-4 w-4" />
                </button>
              </div>
            </form>
          </div>
        ) : (
          /* Empty State */
          <div className="flex h-full flex-col items-center justify-center gap-3 text-xs text-slate-500">
            <p>左側のメニューからエージェントを選択するか、「＋ 新規作成」ボタンを押してください。</p>
            {leftPaneCollapsed && (
              <button
                type="button"
                onClick={() => setLeftPaneCollapsed(false)}
                className="hidden items-center gap-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:inline-flex"
                aria-label="サイドバーを展開"
              >
                <ChevronRight className="h-3.5 w-3.5" />
                エージェントを選択
              </button>
            )}
            <button
              type="button"
              onClick={() => setLeftPaneOpen(true)}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
            >
              エージェントを選択
            </button>
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
