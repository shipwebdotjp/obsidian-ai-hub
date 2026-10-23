import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ChevronRight } from "lucide-react";
import { readPromptDraft, useSessionPromptDraft } from "../../hooks/useSessionPromptDraft";
import { AgentSidebar } from "./AgentSidebar";
import { AgentFormPanel } from "./AgentFormPanel";
import { AgentWorkspaceHeader } from "./AgentWorkspaceHeader";
import { AgentMessageList } from "./AgentMessageList";
import { AgentChatInput } from "./AgentChatInput";
import { AgentModals } from "./AgentModals";
import { useAgentsCatalog } from "./useAgentsCatalog";
import { useAgentSessions } from "./useAgentSessions";
import SplitHandle from "../../components/SplitHandle";
import { usePaneResize } from "../../hooks/usePaneResize";
import { useAgentChat } from "./useAgentChat";
import { useAgentTemplates } from "./useAgentTemplates";
import { useAgentsUiState } from "./useAgentsUiState";
import { agentNewChatPath } from "../../constants/routes";

export default function AgentsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const sessionIdParam = searchParams.get("session_id");
  const promptParam = searchParams.get("prompt");
  const [actionError, setActionError] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [shortcutUrlCopied, setShortcutUrlCopied] = useState(false);
  const shortcutUrlResetRef = useRef<number | null>(null);
  const focusChatInput = Boolean(
    (location.state as { focusChatInput?: boolean } | null)?.focusChatInput,
  );

  // Holds the session_id to honor after sessions are loaded for the resolved agent.
  // Cleared after consumption so subsequent agent switches do not re-select it.
  const pendingSessionIdRef = useRef<string | null>(null);
  // Origin of the pending session_id: deep links use the URL param, storage
  // restores use localStorage. Invalid IDs are handled per origin (URL param
  // removal vs. stored value erasure) so the two causes are never confused.
  const pendingSourceRef = useRef<"deeplink" | "storage" | null>(null);
  // Storage-restore target until its detail load settles. Used to erase an
  // unrestorable stored value and fall back without touching normal selections.
  const storageRestoreIdRef = useRef<string | null>(null);
  // Async question-card operations must not leak into the newly selected
  // session after a switch; track the current selection in a ref.
  const selectedSessionIdRef = useRef<string | null>(null);
  // ?prompt=... の消費キー。同一セッションへの再適用を一度だけにする。
  const consumedPromptRef = useRef<string | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  // Vault ピッカーを開く前のパレット破棄状態。閉じる時に復元する。
  const paletteDismissedBeforePickerRef = useRef(false);

  const catalog = useAgentsCatalog({
    sessionIdParam,
    setSearchParams,
    pendingSessionIdRef,
    pendingSourceRef,
    storageRestoreIdRef,
    onActionError: setActionError,
    loadPromptTemplates: (...args) => templates.loadPromptTemplates(...args),
    onCreateFormOpened: () => templates.resetForCreate(),
  });

  const sessions = useAgentSessions({
    selectedAgentId: catalog.selectedAgentId,
    setSelectedAgentId: catalog.setSelectedAgentId,
    selectedSessionIdRef,
    onActionError: setActionError,
    onChatError: setChatError,
    setSearchParams,
    pendingSessionIdRef,
    pendingSourceRef,
    storageRestoreIdRef,
    closeMobileDrawer: () => ui.setLeftPaneOpen(false),
  });

  useEffect(() => {
    selectedSessionIdRef.current = sessions.selectedSessionId;
  }, [sessions.selectedSessionId]);

  useEffect(() => {
    setShortcutUrlCopied(false);
    if (shortcutUrlResetRef.current !== null) {
      window.clearTimeout(shortcutUrlResetRef.current);
      shortcutUrlResetRef.current = null;
    }
  }, [catalog.selectedAgentId]);

  useEffect(() => {
    return () => {
      if (shortcutUrlResetRef.current !== null) {
        window.clearTimeout(shortcutUrlResetRef.current);
        shortcutUrlResetRef.current = null;
      }
    };
  }, []);

  // Chat stream state
  // プロンプト下書きはセッションごとに sessionStorage へデバウンス保存・復元する。
  // 保存対象は入力テキストのみ（添付画像・APIキー等の秘密情報は含めない）。
  const {
    draft: inputText,
    setDraft: setInputText,
    setLocalDraft: setPromptInputLocal,
    saveDraftFor: savePromptDraftFor,
    removeDraftFor: removePromptDraftFor,
  } = useSessionPromptDraft("agents", sessions.selectedSessionId);

  // ?prompt=... があれば、確定済みセッションの入力欄へ一度だけ流し込む。
  // 自動送信はしない。既存の入力・保存済み下書きは上書きしない。
  // 消費後はクエリから除去し、履歴や共有 URL に残さない。
  useEffect(() => {
    if (!promptParam) return;
    const sid = sessions.selectedSessionId;
    if (!sid || sessions.loadedSessionId !== sid) return;
    const key = `${sid}\u0000${promptParam}`;
    if (consumedPromptRef.current !== key) {
      consumedPromptRef.current = key;
      if (inputText === "" && readPromptDraft("agents", sid) === "") {
        setInputText(promptParam);
      }
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("prompt");
        return next;
      },
      { replace: true },
    );
  }, [
    promptParam,
    sessions.selectedSessionId,
    sessions.loadedSessionId,
    inputText,
    setInputText,
    setSearchParams,
  ]);

  const chat = useAgentChat({
    selectedSessionId: sessions.selectedSessionId,
    selectedAgentId: catalog.selectedAgentId,
    activeAgent: catalog.activeAgent,
    onChatError: setChatError,
    loadSessions: sessions.loadSessions,
    loadSessionDetail: sessions.loadSessionDetail,
    messages: sessions.messages,
    setMessages: sessions.setMessages,
    runs: sessions.runs,
    loadedSessionId: sessions.loadedSessionId,
    activeWaitingRun: sessions.activeWaitingRun,
    setActiveWaitingRun: sessions.setActiveWaitingRun,
    setSessions: sessions.setSessions,
    inputText,
    savePromptDraftFor,
    setPromptInputLocal,
    removePromptDraftFor,
    imageInputRef,
  });

  const templates = useAgentTemplates({
    selectedSessionIdRef,
    setSelectedSkill: chat.setSelectedSkill,
    setInputText,
    selectedAgentId: catalog.selectedAgentId,
    activeAgent: catalog.activeAgent,
    isCreatingAgent: catalog.isCreatingAgent,
    isEditingAgent: catalog.isEditingAgent,
    selectedSessionId: sessions.selectedSessionId,
    isStreaming: chat.isStreaming,
    inputText,
  });

  const ui = useAgentsUiState({
    messages: sessions.messages,
    streamingText: chat.streamingText,
    streamingToolCalls: chat.streamingToolCalls,
    streamingPhase: chat.streamingPhase,
    streamingIteration: chat.streamingIteration,
    activeWaitingRun: sessions.activeWaitingRun,
    activeSessionMenuId: sessions.activeSessionMenuId,
    setActiveSessionMenuId: sessions.setActiveSessionMenuId,
    setAgentToDelete: catalog.setAgentToDelete,
    setSessionToDelete: sessions.setSessionToDelete,
    setSessionToEditTitle: sessions.setSessionToEditTitle,
    agentToDelete: catalog.agentToDelete,
    sessionToDelete: sessions.sessionToDelete,
    sessionToEditTitle: sessions.sessionToEditTitle,
    isFormOpen: catalog.isCreatingAgent || catalog.isEditingAgent,
    onCloseForm: catalog.closeAgentForm,
  });

  // Load sessions when selected agent changes
  useEffect(() => {
    chat.abortSubscriptionAndReset();
    void sessions.handleAgentChanged(catalog.selectedAgentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog.selectedAgentId]);

  // Load session detail messages when session changes
  // Subscription-only abort: switching sessions never cancels the run.
  useEffect(() => {
    chat.abortSubscriptionAndReset();

    if (!sessions.selectedSessionId) {
      sessions.resetForEmptySession();
      setInputText("");
      if (imageInputRef.current) {
        imageInputRef.current.value = "";
      }
      templates.syncForSession(null);
      return;
    }
    sessions.setLoadedSessionId(null);
    void sessions.loadSessionDetail(sessions.selectedSessionId);
    chat.setHitlLinks([]);
    // 入力テキスト・添付画像の下書きは各 hook がセッション切替時に復元する。
    if (imageInputRef.current) {
      imageInputRef.current.value = "";
    }
    templates.syncForSession(sessions.selectedSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.selectedSessionId]);

  const handleSelectAgentRow = (agentId: string) => {
    catalog.selectAgent(agentId);
    ui.setLeftPaneOpen(false);
    // Switching agents invalidates the current session; clear the URL param.
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("session_id");
        return next;
      },
      { replace: true },
    );
  };

  const handleSelectSession = (sessionId: string) => {
    sessions.handleSelectSession(sessionId);
    ui.setLeftPaneOpen(false);
  };

  // 「＋ 新しい会話」ボタンからの作成成功後は、読み込み完了時に入力欄へフォーカスする。
  // ref ではなく state で保持し、設定時に確実に再レンダーを起こす。
  const [focusAfterCreate, setFocusAfterCreate] = useState(false);
  const handleCreateSessionAndFocus = () => {
    void sessions.handleCreateSession().then((createdId) => {
      if (createdId) setFocusAfterCreate(true);
    });
  };

  const handleOpenEditForm = (agent: Parameters<typeof catalog.handleOpenEditForm>[0]) => {
    catalog.handleOpenEditForm(agent);
    templates.resetForEdit();
  };

  const handleCopyShortcutUrl = async (agentId: string) => {
    setActionError(null);
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("clipboard unavailable");
      }
      await navigator.clipboard.writeText(
        new URL(agentNewChatPath(agentId), window.location.origin).toString(),
      );
      setShortcutUrlCopied(true);
      if (shortcutUrlResetRef.current !== null) {
        window.clearTimeout(shortcutUrlResetRef.current);
      }
      shortcutUrlResetRef.current = window.setTimeout(() => {
        setShortcutUrlCopied(false);
        shortcutUrlResetRef.current = null;
      }, 2000);
    } catch (error) {
      console.error("Failed to copy agent shortcut URL:", error);
      setShortcutUrlCopied(false);
      setActionError("ショートカットURLのコピーに失敗しました。");
    }
  };

  const handleAutoFocusComplete = () => {
    setFocusAfterCreate(false);
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  };

  const { activeAgent } = catalog;
  const isFormOpen = catalog.isCreatingAgent || catalog.isEditingAgent;

  const { containerRef, paneRef, containerStyle, isDragging, handleProps } = usePaneResize({
    defaultSize: "16rem",
    minSize: 220,
    minOther: 400,
    storageKey: "agents",
  });

  return (
    <div
      ref={containerRef}
      style={containerStyle}
      className="flex h-full flex-col bg-slate-50 lg:flex-row"
    >
      <AgentSidebar
        desktopPaneRef={paneRef}
        agents={catalog.agents}
        selectedAgentId={catalog.selectedAgentId}
        isCreatingAgent={catalog.isCreatingAgent}
        isEditingAgent={catalog.isEditingAgent}
        actionError={actionError}
        onOpenCreateForm={catalog.handleOpenCreateForm}
        onSelectAgentRow={handleSelectAgentRow}
        onToggleAgentPin={catalog.handleToggleAgentPin}
        sessions={sessions.sessions}
        selectedSessionId={sessions.selectedSessionId}
        onSelectSession={handleSelectSession}
        onCreateSession={handleCreateSessionAndFocus}
        sessionSearchQuery={sessions.sessionSearchQuery}
        onSessionSearchQueryChange={sessions.setSessionSearchQuery}
        sessionSearchResults={sessions.sessionSearchResults}
        isSessionSearchLoading={sessions.isSessionSearchLoading}
        sessionSearchError={sessions.sessionSearchError}
        onSelectSearchResult={sessions.handleSelectSearchResult}
        activeSessionMenuId={sessions.activeSessionMenuId}
        onToggleSessionMenu={(id) =>
          sessions.setActiveSessionMenuId((current) => (current === id ? null : id))
        }
        onToggleSessionPin={(s, e) => {
          sessions.setActiveSessionMenuId(null);
          sessions.handleToggleSessionPin(s, e);
        }}
        onOpenEditTitle={sessions.handleOpenEditTitle}
        onDeleteSessionTarget={(s) => {
          sessions.setActiveSessionMenuId(null);
          sessions.setSessionToDelete(s);
        }}
        leftPaneOpen={ui.leftPaneOpen}
        onCloseDrawer={() => ui.setLeftPaneOpen(false)}
        mobileDrawerCloseRef={ui.mobileDrawerCloseRef}
        mobileDrawerRef={ui.mobileDrawerRef}
        leftPaneCollapsed={ui.leftPaneCollapsed}
        onCollapsePane={() => ui.setLeftPaneCollapsed(true)}
      />

      {!ui.leftPaneCollapsed && (
        <SplitHandle handleProps={handleProps} isDragging={isDragging} />
      )}

      {/* Main Content Area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {isFormOpen ? (
          /* Agent Create / Edit Form */
          <AgentFormPanel
            isCreatingAgent={catalog.isCreatingAgent}
            isEditingAgent={catalog.isEditingAgent}
            activeAgent={activeAgent}
            selectedAgentId={catalog.selectedAgentId}
            onDeleteAgentTarget={catalog.setAgentToDelete}
            onCloseForm={catalog.closeAgentForm}
            formError={catalog.formError}
            onSaveAgent={catalog.handleSaveAgent}
            formName={catalog.formName}
            onFormNameChange={catalog.setFormName}
            formPrompt={catalog.formPrompt}
            onFormPromptChange={catalog.setFormPrompt}
            formProvider={catalog.formProvider}
            onFormProviderChange={catalog.setFormProvider}
            formModel={catalog.formModel}
            onFormModelChange={catalog.setFormModel}
            isAdvancedOpen={catalog.isAdvancedOpen}
            onAdvancedOpenChange={catalog.setIsAdvancedOpen}
            formMaxTokens={catalog.formMaxTokens}
            onFormMaxTokensChange={catalog.setFormMaxTokens}
            formReasoningEffort={catalog.formReasoningEffort}
            onFormReasoningEffortChange={catalog.setFormReasoningEffort}
            availableTools={catalog.availableTools}
            formToolIds={catalog.formToolIds}
            onFormToolIdsChange={catalog.setFormToolIds}
            agents={catalog.agents}
            formDelegateAgentIds={catalog.formDelegateAgentIds}
            onFormDelegateAgentIdsChange={catalog.setFormDelegateAgentIds}
            formDefaultVaultIds={catalog.formDefaultVaultIds}
            onFormDefaultVaultIdsChange={catalog.setFormDefaultVaultIds}
            copiedAgentId={catalog.copiedAgentId}
            agentIdCopyError={catalog.agentIdCopyError}
            onCopyAgentId={catalog.handleCopyAgentId}
            promptTemplates={templates.promptTemplates}
            templateLoading={templates.templateLoading}
            templateError={templates.templateError}
            editingTemplateId={templates.editingTemplateId}
            onEditTemplate={templates.handleEditTemplate}
            onDeleteTemplate={templates.handleDeleteTemplate}
            onCreateOrUpdateTemplate={templates.handleCreateOrUpdateTemplate}
            templateFormName={templates.templateFormName}
            onTemplateFormNameChange={templates.setTemplateFormName}
            templateFormContent={templates.templateFormContent}
            onTemplateFormContentChange={templates.setTemplateFormContent}
            onCancelEditTemplate={() => {
              templates.setEditingTemplateId(null);
              templates.setTemplateFormName("");
              templates.setTemplateFormContent("");
              templates.setTemplateError(null);
            }}
          />
        ) : activeAgent ? (
          /* Active Agent Workspace */
          <div className="flex flex-1 flex-col overflow-hidden">
            <AgentWorkspaceHeader
              activeAgent={activeAgent}
              leftPaneCollapsed={ui.leftPaneCollapsed}
              onExpandPane={() => ui.setLeftPaneCollapsed(false)}
              mobileDrawerTriggerRef={ui.mobileDrawerTriggerRef}
              onOpenDrawer={() => ui.setLeftPaneOpen(true)}
              onOpenEditForm={handleOpenEditForm}
              onCopyShortcutUrl={handleCopyShortcutUrl}
              shortcutUrlCopied={shortcutUrlCopied}
            />

            {/* Chat Messages View */}
            <AgentMessageList
              messages={sessions.messages}
              isStreaming={chat.isStreaming}
              runs={sessions.runs}
              answerHistory={sessions.answerHistory}
              activeWaitingRun={sessions.activeWaitingRun}
              streamingToolCalls={chat.streamingToolCalls}
              displayedStreamingPhase={chat.displayedStreamingPhase}
              streamingIteration={chat.streamingIteration}
              streamingText={chat.streamingText}
              hitlLinks={chat.hitlLinks}
              chatError={chatError}
              copiedMessageId={chat.copiedMessageId}
              onCopyMessage={chat.handleCopyMessage}
              onSubmitWaitingAnswers={sessions.handleSubmitWaitingAnswers}
              onCancelWaitingRun={sessions.handleCancelWaitingRun}
              queuedMessages={chat.queuedMessages}
              onRemoveQueuedMessage={chat.handleRemoveQueuedMessage}
              onRetryQueuedMessage={chat.handleRetryQueuedMessage}
              messageRefs={sessions.messageElementRefs}
              messagesEndRef={ui.messagesEndRef}
            />

            {/* Input Footer */}
            <AgentChatInput
              inputText={inputText}
              onInputTextChange={setInputText}
              isStreaming={chat.isStreaming}
              queuedCount={chat.queuedMessages.length}
              selectedSessionId={sessions.selectedSessionId}
              activeAgent={activeAgent}
              isDragOver={chat.isDragOver}
              pendingAttachments={chat.pendingAttachments}
              onRemoveAttachment={chat.handleRemoveAttachment}
              pendingContextRefs={chat.pendingContextRefs}
              onRemoveContextRef={chat.handleRemoveContextRef}
              onToggleContextRef={chat.handleToggleContextRef}
              vaultPickerOpen={chat.vaultPickerOpen}
              onOpenVaultPicker={() => {
                paletteDismissedBeforePickerRef.current =
                  templates.isCommandPaletteDismissed;
                templates.setIsCommandPaletteDismissed(true);
                chat.setVaultPickerOpen(true);
              }}
              onCloseVaultPicker={() => {
                chat.setVaultPickerOpen(false);
                templates.setIsCommandPaletteDismissed(
                  paletteDismissedBeforePickerRef.current,
                );
              }}
              selectedSkill={chat.selectedSkill}
              onClearSkill={() => chat.setSelectedSkill(null)}
              isPaletteActive={templates.isPaletteActive}
              filteredCandidates={templates.filteredCandidates}
              skillCandidates={templates.skillCandidates}
              templateCandidates={templates.templateCandidates}
              paletteOrderedCandidates={templates.paletteOrderedCandidates}
              paletteSelectedIndex={templates.paletteSelectedIndex}
              onPaletteSelectedIndexChange={templates.setPaletteSelectedIndex}
              hasSkillsTool={templates.hasSkillsTool}
              onSelectCandidate={templates.handleSelectCandidate}
              onSelectTemplate={templates.handleSelectTemplate}
              plusMenuOpen={templates.plusMenuOpen}
              onTogglePlusMenu={() => {
                templates.setPlusMenuOpen((v) => !v);
                templates.setTemplateSelectorOpen(false);
              }}
              onOpenTemplateSelector={() => {
                templates.setTemplateSelectorOpen(true);
                templates.setPlusMenuOpen(false);
              }}
              templateSelectorOpen={templates.templateSelectorOpen}
              promptTemplates={templates.promptTemplates}
              attachmentReadsPending={chat.attachmentReadsPending}
              imageInputRef={imageInputRef}
              onClosePlusMenu={() => {
                templates.setPlusMenuOpen(false);
                templates.setTemplateSelectorOpen(false);
              }}
              onFilesSelected={chat.handleFilesSelected}
              onSend={chat.submitMessageViaRun}
              onCancelRun={() => void chat.handleCancelAgentRun()}
              onDismissPalette={() => templates.setIsCommandPaletteDismissed(true)}
              onPaste={chat.handleInputPaste}
              onFormDragOver={chat.handleFormDragOver}
              onFormDragLeave={chat.handleFormDragLeave}
              onFormDrop={chat.handleFormDrop}
              shouldAutoFocus={
                (focusChatInput || focusAfterCreate) &&
                sessions.selectedSessionId !== null &&
                sessions.loadedSessionId === sessions.selectedSessionId
              }
              onAutoFocusComplete={handleAutoFocusComplete}
            />
          </div>
        ) : (
          /* Empty State */
          <div className="flex h-full flex-col items-center justify-center gap-3 text-xs text-slate-500">
            <p>左側のメニューからエージェントを選択するか、「＋ 新規作成」ボタンを押してください。</p>
            {ui.leftPaneCollapsed && (
              <button
                type="button"
                onClick={() => ui.setLeftPaneCollapsed(false)}
                className="hidden items-center gap-1 rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:inline-flex"
                aria-label="サイドバーを展開"
              >
                <ChevronRight className="h-3.5 w-3.5" />
                エージェントを選択
              </button>
            )}
            <button
              type="button"
              onClick={() => ui.setLeftPaneOpen(true)}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
            >
              エージェントを選択
            </button>
          </div>
        )}
      </div>

      <AgentModals
        agentToDelete={catalog.agentToDelete}
        onCloseDeleteAgent={() => catalog.setAgentToDelete(null)}
        onConfirmDeleteAgent={catalog.handleDeleteAgentConfirm}
        sessionToEditTitle={sessions.sessionToEditTitle}
        onCloseEditTitle={() => sessions.setSessionToEditTitle(null)}
        editTitleError={sessions.editTitleError}
        editTitleText={sessions.editTitleText}
        onEditTitleTextChange={sessions.setEditTitleText}
        onSaveSessionTitle={sessions.handleSaveSessionTitle}
        sessionToDelete={sessions.sessionToDelete}
        onCloseDeleteSession={() => sessions.setSessionToDelete(null)}
        onConfirmDeleteSession={sessions.handleDeleteSessionConfirm}
      />
    </div>
  );
}
