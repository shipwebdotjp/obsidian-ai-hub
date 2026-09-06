import { useCallback, useEffect, useMemo, useState, type MutableRefObject } from "react";
import {
  createPromptTemplate,
  deletePromptTemplate,
  getAgentSlashCandidates,
  listPromptTemplates,
  updatePromptTemplate,
} from "../../api/client";
import type {
  Agent,
  AgentPromptTemplate,
  SlashCandidate,
  SlashInvocation,
} from "../../api/types";
import {
  filterSlashCandidates,
  toClientTemplateCandidates,
} from "./agentViewUtils";

interface UseAgentTemplatesOptions {
  selectedSessionIdRef: MutableRefObject<string | null>;
  setSelectedSkill: React.Dispatch<React.SetStateAction<SlashInvocation | null>>;
  setInputText: (text: string) => void;
  selectedAgentId: string | null;
  activeAgent: Agent | undefined;
  isCreatingAgent: boolean;
  isEditingAgent: boolean;
  selectedSessionId: string | null;
  isStreaming: boolean;
  inputText: string;
}

/** プロンプトテンプレートとスラッシュ候補パレットを管理する。 */
export function useAgentTemplates({
  selectedSessionIdRef,
  setSelectedSkill,
  setInputText,
  selectedAgentId,
  activeAgent,
  isCreatingAgent,
  isEditingAgent,
  selectedSessionId,
  isStreaming,
  inputText,
}: UseAgentTemplatesOptions) {
  const [promptTemplates, setPromptTemplates] = useState<AgentPromptTemplate[]>([]);
  const [serverCandidates, setServerCandidates] = useState<SlashCandidate[]>([]);
  const [hasSkillsTool, setHasSkillsTool] = useState(true);
  const [templateSelectorOpen, setTemplateSelectorOpen] = useState(false);
  const [plusMenuOpen, setPlusMenuOpen] = useState(false);
  const [templateFormName, setTemplateFormName] = useState("");
  const [templateFormContent, setTemplateFormContent] = useState("");
  const [editingTemplateId, setEditingTemplateId] = useState<string | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [isCommandPaletteDismissed, setIsCommandPaletteDismissed] = useState(false);
  const [paletteSelectedIndex, setPaletteSelectedIndex] = useState(0);

  const loadPromptTemplates = useCallback(async (agentId: string) => {
    setTemplateLoading(true);
    try {
      const res = await listPromptTemplates(agentId);
      setPromptTemplates(res.templates);
    } catch {
      // Stale templates from another agent must not linger as if they belong
      // to the requested agent.
      setPromptTemplates([]);
    } finally {
      setTemplateLoading(false);
    }
  }, []);

  const loadSlashCandidates = useCallback(async (sessionId: string) => {
    try {
      const res = await getAgentSlashCandidates(sessionId);
      if (selectedSessionIdRef.current !== sessionId) return;
      setServerCandidates(res.candidates || []);
      setHasSkillsTool(res.has_skills_tool);
      if (!res.has_skills_tool) setSelectedSkill(null);
    } catch {
      if (selectedSessionIdRef.current !== sessionId) return;
      setServerCandidates([]);
      setHasSkillsTool(true);
    }
  }, [selectedSessionIdRef, setSelectedSkill]);

  /** セッション切替時の候補同期（選択なしでは空に戻す）。 */
  const syncForSession = (sessionId: string | null) => {
    if (!sessionId) {
      setServerCandidates([]);
      setHasSkillsTool(true);
      setSelectedSkill(null);
      return;
    }
    setServerCandidates([]);
    void loadSlashCandidates(sessionId);
    setSelectedSkill(null);
  };

  /** 新規作成フォームを開いた際のテンプレート状態リセット。 */
  const resetForCreate = () => {
    setPromptTemplates([]);
    setTemplateFormName("");
    setTemplateFormContent("");
    setEditingTemplateId(null);
    setTemplateError(null);
  };

  const resetForEdit = () => {
    setPromptTemplates([]);
    setTemplateFormName("");
    setTemplateFormContent("");
    setEditingTemplateId(null);
    setTemplateError(null);
  };

  const handleSelectTemplate = (content: string) => {
    setInputText(content);
    setTemplateSelectorOpen(false);
    setPlusMenuOpen(false);
    setIsCommandPaletteDismissed(true);
  };

  useEffect(() => {
    if (!inputText.startsWith("/")) {
      setIsCommandPaletteDismissed(false);
    }
    setPaletteSelectedIndex(0);
  }, [inputText]);

  const clientTemplateCandidates = useMemo<SlashCandidate[]>(
    () => toClientTemplateCandidates(promptTemplates),
    [promptTemplates],
  );

  const allCandidates = useMemo(
    () => [...serverCandidates, ...clientTemplateCandidates],
    [serverCandidates, clientTemplateCandidates],
  );

  const isPaletteActive =
    Boolean(activeAgent) &&
    Boolean(selectedSessionId) &&
    !isStreaming &&
    inputText.startsWith("/") &&
    !isCommandPaletteDismissed;

  const filteredCandidates = useMemo(
    () => (isPaletteActive ? filterSlashCandidates(allCandidates, inputText) : []),
    [isPaletteActive, allCandidates, inputText],
  );

  const skillCandidates = useMemo(
    () => filteredCandidates.filter((c) => c.kind === "skill"),
    [filteredCandidates],
  );

  const templateCandidates = useMemo(
    () => filteredCandidates.filter((c) => c.kind === "template"),
    [filteredCandidates],
  );

  // Visual order is grouped (skills, then templates). Keyboard navigation
  // and highlight must follow visual order, not the interleaved relevance
  // order of filteredCandidates.
  const paletteOrderedCandidates = useMemo(
    () => [...skillCandidates, ...templateCandidates],
    [skillCandidates, templateCandidates],
  );

  const handleSelectCandidate = (candidate: SlashCandidate) => {
    if (candidate.kind === "skill") {
      setSelectedSkill({ kind: "skill", name: candidate.name });
      setInputText("");
      setIsCommandPaletteDismissed(true);
    } else if (candidate.kind === "template") {
      setSelectedSkill(null);
      setInputText(candidate.content || "");
      setTemplateSelectorOpen(false);
      setPlusMenuOpen(false);
      setIsCommandPaletteDismissed(true);
    }
  };

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
    } catch (err: unknown) {
      setTemplateError(err instanceof Error ? err.message : "テンプレートの保存に失敗しました。");
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
    } catch (err: unknown) {
      setTemplateError(err instanceof Error ? err.message : "テンプレートの削除に失敗しました。");
    }
  };

  const handleEditTemplate = (t: AgentPromptTemplate) => {
    setEditingTemplateId(t.template_id);
    setTemplateFormName(t.name);
    setTemplateFormContent(t.content);
    setTemplateError(null);
  };

  return {
    promptTemplates,
    serverCandidates,
    hasSkillsTool,
    templateSelectorOpen,
    setTemplateSelectorOpen,
    plusMenuOpen,
    setPlusMenuOpen,
    templateFormName,
    setTemplateFormName,
    templateFormContent,
    setTemplateFormContent,
    editingTemplateId,
    setEditingTemplateId,
    templateError,
    setTemplateError,
    templateLoading,
    isCommandPaletteDismissed,
    setIsCommandPaletteDismissed,
    paletteSelectedIndex,
    setPaletteSelectedIndex,
    loadPromptTemplates,
    loadSlashCandidates,
    syncForSession,
    resetForCreate,
    resetForEdit,
    handleSelectTemplate,
    handleSelectCandidate,
    clientTemplateCandidates,
    allCandidates,
    isPaletteActive,
    filteredCandidates,
    skillCandidates,
    templateCandidates,
    paletteOrderedCandidates,
    handleCreateOrUpdateTemplate,
    handleDeleteTemplate,
    handleEditTemplate,
  };
}
