import { useEffect, useRef, useState, type MutableRefObject } from "react";
import type { SetURLSearchParams } from "react-router-dom";
import {
  createAgent,
  deleteAgent,
  getAgentSessionDetail,
  listAgents,
  listAgentTools,
  updateAgent,
} from "../../api/client";
import type { Agent, AgentTool } from "../../api/types";
import {
  clearLastViewedSessionId,
  readLastViewedSessionId,
} from "./lastViewedSession";
import { AGENT_DELEGATE_TOOL_ID } from "./agentViewUtils";

interface UseAgentsCatalogOptions {
  sessionIdParam: string | null;
  setSearchParams: SetURLSearchParams;
  pendingSessionIdRef: MutableRefObject<string | null>;
  pendingSourceRef: MutableRefObject<"deeplink" | "storage" | null>;
  storageRestoreIdRef: MutableRefObject<string | null>;
  onActionError: (message: string | null) => void;
  loadPromptTemplates: (agentId: string) => Promise<void>;
  /** 新規作成フォームを開いた際のテンプレート状態リセット（templates hook 所有）。 */
  onCreateFormOpened: () => void;
}

/** エージェント一覧・選択・作成/編集フォーム・削除を管理する。 */
export function useAgentsCatalog({
  sessionIdParam,
  setSearchParams,
  pendingSessionIdRef,
  pendingSourceRef,
  storageRestoreIdRef,
  onActionError,
  loadPromptTemplates,
  onCreateFormOpened,
}: UseAgentsCatalogOptions) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [availableTools, setAvailableTools] = useState<AgentTool[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Agent form state
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [isCreatingAgent, setIsCreatingAgent] = useState(false);
  const [formName, setFormName] = useState("");
  const [formPrompt, setFormPrompt] = useState("");
  const [formProvider, setFormProvider] = useState("");
  const [formModel, setFormModel] = useState("");
  const [formToolIds, setFormToolIds] = useState<string[]>([]);
  const [formDelegateAgentIds, setFormDelegateAgentIds] = useState<string[]>([]);
  const [formMaxTokens, setFormMaxTokens] = useState<string>("");
  const [formReasoningEffort, setFormReasoningEffort] = useState<string>("");
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);
  const [copiedAgentId, setCopiedAgentId] = useState(false);
  const [agentIdCopyError, setAgentIdCopyError] = useState<string | null>(null);
  const agentIdCopyResetRef = useRef<number | null>(null);

  // Load agents & catalog tools on mount
  useEffect(() => {
    loadAgentsAndTools();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadAgentsAndTools = async () => {
    onActionError(null);
    try {
      const [agRes, toolRes] = await Promise.all([
        listAgents(),
        listAgentTools(),
      ]);
      setAgents(agRes.agents);
      setAvailableTools(toolRes.tools);

      // Deep link: resolve the agent from the URL's session_id, then let the
      // selectedAgentId effect load the session list and consume pendingSessionIdRef.
      // A valid deep link always wins; the stored last-viewed session is only
      // used when the URL has no session_id.
      if (sessionIdParam) {
        pendingSessionIdRef.current = sessionIdParam;
        pendingSourceRef.current = "deeplink";
        try {
          const detail = await getAgentSessionDetail(sessionIdParam);
          setSelectedAgentId(detail.agent.agent_id);
          return;
        } catch {
          // Stale or invalid session_id: fall back to first agent and clear the param.
          pendingSessionIdRef.current = null;
          pendingSourceRef.current = null;
          setSearchParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.delete("session_id");
              return next;
            },
            { replace: true },
          );
        }
      } else {
        // ID-less entry: restore the last-viewed session from localStorage.
        // Validate existence and resolve the owning agent exactly like a deep
        // link so cross-agent restores open the right agent. Storage failures
        // or invalid values silently fall through to the first agent.
        const storedSessionId = readLastViewedSessionId();
        if (storedSessionId) {
          pendingSessionIdRef.current = storedSessionId;
          pendingSourceRef.current = "storage";
          try {
            const detail = await getAgentSessionDetail(storedSessionId);
            storageRestoreIdRef.current = storedSessionId;
            setSelectedAgentId(detail.agent.agent_id);
            return;
          } catch {
            // Unrestorable stored value: erase it and fall back to first agent.
            clearLastViewedSessionId();
            pendingSessionIdRef.current = null;
            pendingSourceRef.current = null;
            storageRestoreIdRef.current = null;
          }
        }
      }

      if (agRes.agents.length > 0 && !selectedAgentId) {
        setSelectedAgentId(agRes.agents[0].agent_id);
      }
    } catch (e: unknown) {
      onActionError(e instanceof Error ? e.message : "エージェントまたはツールの読み込みに失敗しました。");
    }
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
    setFormDelegateAgentIds([]);
    setFormMaxTokens("");
    setFormReasoningEffort("");
    setIsAdvancedOpen(false);
    setFormError(null);
    onActionError(null);
    onCreateFormOpened();
  };

  const handleOpenEditForm = (agent: Agent) => {
    setIsEditingAgent(true);
    setIsCreatingAgent(false);
    setFormName(agent.name);
    setFormPrompt(agent.system_prompt);
    setFormProvider(agent.provider || "");
    setFormModel(agent.model || "");
    setFormToolIds(agent.tool_ids || []);
    setFormDelegateAgentIds(agent.delegate_agent_ids || []);
    const adv = agent.advanced_params ?? {};
    setFormMaxTokens(adv.max_tokens != null ? String(adv.max_tokens) : "");
    setFormReasoningEffort(adv.reasoning?.effort ?? "");
    setIsAdvancedOpen(Boolean(adv.max_tokens != null || adv.reasoning?.effort));
    setFormError(null);
    onActionError(null);
    setCopiedAgentId(false);
    setAgentIdCopyError(null);
    // Load templates for this agent
    void loadPromptTemplates(agent.agent_id);
  };

  const buildAdvancedParams = (): { max_tokens?: number; reasoning?: { effort?: string } } | null => {
    const params: { max_tokens?: number; reasoning?: { effort?: string } } = {};
    const mt = formMaxTokens.trim();
    if (mt !== "") {
      const n = Number(mt);
      if (!Number.isInteger(n) || n <= 0) return null;
      params.max_tokens = n;
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
    onActionError(null);
    const advanced_params = buildAdvancedParams();
    if (advanced_params === null) {
      setFormError("最大トークン数は1以上の整数を入力してください。");
      return;
    }
    const isDelegateSelected = formToolIds.includes(AGENT_DELEGATE_TOOL_ID);
    const delegate_agent_ids = isDelegateSelected ? formDelegateAgentIds : [];

    try {
      if (isCreatingAgent) {
        const res = await createAgent({
          name: formName,
          system_prompt: formPrompt,
          provider: formProvider || undefined,
          model: formModel || undefined,
          tool_ids: formToolIds,
          delegate_agent_ids,
          advanced_params: Object.keys(advanced_params).length ? advanced_params : undefined,
        });
        setAgents((prev) => [res.agent, ...prev]);
        setSelectedAgentId(res.agent.agent_id);
      } else if (isEditingAgent && selectedAgentId) {
        const res = await updateAgent(selectedAgentId, {
          name: formName,
          system_prompt: formPrompt,
          provider: formProvider,
          model: formModel,
          tool_ids: formToolIds,
          delegate_agent_ids,
          advanced_params,
        });
        setAgents((prev) =>
          prev.map((a) => (a.agent_id === selectedAgentId ? res.agent : a))
        );
      }
      setIsCreatingAgent(false);
      setIsEditingAgent(false);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "エージェントの保存に失敗しました。");
    }
  };

  const handleDeleteAgentConfirm = async () => {
    if (!agentToDelete) return;
    const deletedId = agentToDelete.agent_id;
    onActionError(null);
    try {
      await deleteAgent(deletedId);
      const remaining = agents.filter((a) => a.agent_id !== deletedId);
      setAgents((prev) => prev.filter((a) => a.agent_id !== deletedId));
      setAgentToDelete(null);
      if (selectedAgentId === deletedId) {
        setSelectedAgentId(remaining.length > 0 ? remaining[0].agent_id : null);
      }
    } catch (e: unknown) {
      onActionError("エージェントの削除に失敗しました: " + (e instanceof Error ? e.message : String(e)));
      setAgentToDelete(null);
    }
  };

  const handleToggleAgentPin = async (agent: Agent, e: React.MouseEvent) => {
    e.stopPropagation();
    onActionError(null);
    try {
      await updateAgent(agent.agent_id, { pinned: !agent.pinned_at });
      const res = await listAgents();
      setAgents(res.agents);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "ピン留めの更新に失敗しました。";
      onActionError(message);
    }
  };

  /** エージェント行クリック時の選択（ドロワー・URL処理は呼び出し側で行う）。 */
  const selectAgent = (agentId: string) => {
    setSelectedAgentId(agentId);
    setIsCreatingAgent(false);
    setIsEditingAgent(false);
  };

  const closeAgentForm = () => {
    setIsCreatingAgent(false);
    setIsEditingAgent(false);
  };

  const handleCopyAgentId = async () => {
    if (!selectedAgentId) return;
    setAgentIdCopyError(null);
    try {
      if (
        typeof navigator === "undefined" ||
        !navigator.clipboard ||
        typeof navigator.clipboard.writeText !== "function"
      ) {
        throw new Error("clipboard unavailable");
      }
      await navigator.clipboard.writeText(selectedAgentId);
      setCopiedAgentId(true);
      if (agentIdCopyResetRef.current !== null) {
        window.clearTimeout(agentIdCopyResetRef.current);
      }
      agentIdCopyResetRef.current = window.setTimeout(() => {
        setCopiedAgentId(false);
        agentIdCopyResetRef.current = null;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy agent ID:", err);
      setCopiedAgentId(false);
      setAgentIdCopyError(
        "IDのコピーに失敗しました。手動で選択してコピーしてください。",
      );
    }
  };

  // Cleanup pending copy-feedback timer on unmount to avoid state updates
  // on an unmounted component.
  useEffect(() => {
    return () => {
      if (agentIdCopyResetRef.current !== null) {
        window.clearTimeout(agentIdCopyResetRef.current);
        agentIdCopyResetRef.current = null;
      }
    };
  }, []);

  // Reset the agent-ID copy feedback when the target agent changes.
  useEffect(() => {
    setCopiedAgentId(false);
    setAgentIdCopyError(null);
    if (agentIdCopyResetRef.current !== null) {
      window.clearTimeout(agentIdCopyResetRef.current);
      agentIdCopyResetRef.current = null;
    }
  }, [selectedAgentId]);

  const activeAgent = agents.find((a) => a.agent_id === selectedAgentId);

  return {
    agents,
    availableTools,
    selectedAgentId,
    setSelectedAgentId,
    activeAgent,
    isEditingAgent,
    isCreatingAgent,
    formName,
    setFormName,
    formPrompt,
    setFormPrompt,
    formProvider,
    setFormProvider,
    formModel,
    setFormModel,
    formToolIds,
    setFormToolIds,
    formDelegateAgentIds,
    setFormDelegateAgentIds,
    formMaxTokens,
    setFormMaxTokens,
    formReasoningEffort,
    setFormReasoningEffort,
    isAdvancedOpen,
    setIsAdvancedOpen,
    formError,
    agentToDelete,
    setAgentToDelete,
    copiedAgentId,
    agentIdCopyError,
    handleOpenCreateForm,
    handleOpenEditForm,
    handleSaveAgent,
    handleDeleteAgentConfirm,
    handleToggleAgentPin,
    handleCopyAgentId,
    selectAgent,
    closeAgentForm,
  };
}
