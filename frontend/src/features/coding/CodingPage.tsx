import { useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useSessionPromptDraft } from "../../hooks/useSessionPromptDraft";
import { CodingSidebar } from "./components/CodingSidebar";
import { CodingConversationHeader } from "./components/CodingConversationHeader";
import { CodingMessageList } from "./components/CodingMessageList";
import { CodingChatInput } from "./components/CodingChatInput";
import { CodingModals } from "./components/CodingModals";
import { useCodingProjects } from "./hooks/useCodingProjects";
import { useCodingSessions } from "./hooks/useCodingSessions";
import { useCodingSessionDetail } from "./hooks/useCodingSessionDetail";
import { useCodingRunStream } from "./hooks/useCodingRunStream";
import { useCodingSlash } from "./hooks/useCodingSlash";
import { useCodingUiState } from "./hooks/useCodingUiState";
import { selectValidProjects } from "./utils/codingSelectors";

export default function CodingPage() {
  const [error, setError] = useState<string | null>(null);

  const projects = useCodingProjects({ onError: setError });
  const sessions = useCodingSessions({
    selectedProjectId: projects.selectedProjectId,
    onError: setError,
    onEmptySessions: () => detail.resetForEmptySession(),
  });

  // 非同期の送信完了・失敗処理が、切替先セッションの入力・下書きへ波及しない
  // よう、現在選択中セッションを ref で追跡する。
  const selectedSessionIdRef = useRef<string | null>(null);
  useEffect(() => {
    selectedSessionIdRef.current = sessions.selectedSessionId;
  }, [sessions.selectedSessionId]);

  // Chat input and streaming state
  // プロンプト下書きはセッションごとに sessionStorage へデバウンス保存・復元する。
  const {
    draft: inputContent,
    setDraft: setInputContent,
    setLocalDraft: setPromptInputLocal,
    saveDraftFor: savePromptDraftFor,
    removeDraftFor: removePromptDraftFor,
  } = useSessionPromptDraft("coding", sessions.selectedSessionId);

  const slash = useCodingSlash({
    selectedSessionIdRef,
    inputContent,
    clearInput: () => setInputContent(""),
  });

  const detail = useCodingSessionDetail({
    selectedSessionId: sessions.selectedSessionId,
    selectedSession: sessions.selectedSession,
    selectedSessionIdRef,
    onError: setError,
    setSessions: sessions.setSessions,
    refreshSlashCandidates: slash.refreshSlashCandidates,
  });

  const stream = useCodingRunStream({
    selectedSessionId: sessions.selectedSessionId,
    selectedSessionIdRef,
    activeRun: detail.activeRun,
    latestRun: detail.latestRun,
    onError: setError,
    loadSessionDetail: detail.loadSessionDetail,
    setMessages: detail.setMessages,
    setActiveRun: detail.setActiveRun,
    setSessions: sessions.setSessions,
    setGitStatus: detail.setGitStatus,
    setActiveWaitingRun: detail.setActiveWaitingRun,
    messages: detail.messages,
    inputContent,
    savePromptDraftFor,
    setPromptInputLocal,
    removePromptDraftFor,
    slashInvocation: slash.slashInvocation,
    clearSlashInvocation: () => slash.setSlashInvocation(null),
  });

  const ui = useCodingUiState({
    messages: detail.messages,
    activePhaseText: stream.activePhaseText,
    streamingToolCalls: stream.streamingToolCalls,
    workerState: stream.workerState,
    activeWaitingRun: detail.activeWaitingRun,
  });

  // Load messages & run details when selected session changes.
  // Subscription-only abort: switching sessions never cancels the run.
  useEffect(() => {
    stream.resetForSessionSwitch();
    detail.setGitStatus(null);
    slash.setSlashInvocation(null);
    if (!sessions.selectedSessionId) {
      detail.resetForEmptySession();
      slash.resetForEmptySession();
      return;
    }
    void detail.loadSessionDetail(sessions.selectedSessionId);
    void slash.loadForSession(sessions.selectedSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.selectedSessionId]);

  const validProjects = selectValidProjects(projects.projects);
  const selectedProjectItem = validProjects.find(
    (p) => p.project.project_id === projects.selectedProjectId,
  );
  const selectedSession = sessions.selectedSession;

  const currentRun = detail.activeRun || detail.latestRun;

  return (
    <div className="flex h-full w-full overflow-hidden bg-slate-50">
      {/* Mobile drawer + desktop collapsible left pane */}
      <CodingSidebar
          mobileDrawerOpen={ui.mobileDrawerOpen}
          onCloseMobileDrawer={() => ui.setMobileDrawerOpen(false)}
          drawerCloseBtnRef={ui.drawerCloseBtnRef}
          mobileDrawerRef={ui.mobileDrawerRef}
          leftPaneCollapsed={ui.leftPaneCollapsed}
          onCollapseLeftPane={() => ui.setLeftPaneCollapsed(true)}
          loadingProjects={projects.loadingProjects}
          validProjects={validProjects}
          selectedProjectId={projects.selectedProjectId}
          onSelectProject={projects.setSelectedProjectId}
          loadingSessions={sessions.loadingSessions}
          sessions={sessions.sessions}
          selectedSessionId={sessions.selectedSessionId}
          onSelectSession={sessions.selectSession}
          selectedProjectItem={selectedProjectItem}
          onOpenNewSession={() => sessions.setIsNewSessionModalOpen(true)}
          onOpenUserDefaults={detail.handleOpenUserDefaults}
          onDeleteSession={sessions.handleDeleteSession}
        />

      {/* Pane 3: Conversation */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-slate-50">
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
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-xs text-slate-400">
            <p>セッションを選択するか、新規セッションを作成してください</p>
            {ui.leftPaneCollapsed && (
              <button
                type="button"
                onClick={() => ui.setLeftPaneCollapsed(false)}
                className="hidden items-center gap-1 rounded border border-slate-300 bg-slate-900 text-white px-3 py-1.5 text-xs hover:bg-slate-800 cursor-pointer lg:inline-flex"
                aria-label="サイドバーを展開"
              >
                <ChevronRight className="h-3.5 w-3.5" />
                プロジェクト / セッションを選択
              </button>
            )}
            <button
              type="button"
              onClick={() => ui.setMobileDrawerOpen(true)}
              className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
            >
              プロジェクト / セッションを選択
            </button>
          </div>
        ) : (
          <>
            <CodingConversationHeader
              selectedSession={selectedSession}
              sessionDetail={detail.sessionDetail}
              gitStatus={detail.gitStatus}
              currentRun={currentRun}
              leftPaneCollapsed={ui.leftPaneCollapsed}
              onExpandLeftPane={() => ui.setLeftPaneCollapsed(false)}
              drawerTriggerBtnRef={ui.drawerTriggerBtnRef}
              onOpenMobileDrawer={() => ui.setMobileDrawerOpen(true)}
              onOpenSessionSettings={detail.openSessionSettings}
              onCancelRun={stream.handleCancelRun}
            />

            <CodingMessageList
              messages={detail.messages}
              loadingMessages={detail.loadingMessages}
              isStreaming={stream.isStreaming}
              sessionDetail={detail.sessionDetail}
              activeRun={detail.activeRun}
              latestRun={detail.latestRun}
              currentRun={currentRun}
              activeWaitingRun={detail.activeWaitingRun}
              streamingToolCalls={stream.streamingToolCalls}
              activePhaseText={stream.activePhaseText}
              workerState={stream.workerState}
              copiedMessageId={ui.copiedMessageId}
              onCopyMessage={ui.handleCopyMessage}
              onSubmitWaitingAnswers={detail.handleSubmitWaitingAnswers}
              onCancelWaitingRun={detail.handleCancelWaitingRun}
              messageEndRef={ui.messageEndRef}
              backend={selectedSession.backend}
            />

            <CodingChatInput
              inputContent={inputContent}
              onInputChange={setInputContent}
              isStreaming={stream.isStreaming}
              currentRun={currentRun}
              showSlashPalette={slash.showSlashPalette}
              hasSkillsTool={slash.hasSkillsTool}
              filteredCandidates={slash.filteredCandidates}
              slashPaletteIndex={slash.slashPaletteIndex}
              onSlashPaletteIndexChange={slash.setSlashPaletteIndex}
              slashInvocation={slash.slashInvocation}
              onClearSlashInvocation={() => slash.setSlashInvocation(null)}
              onSelectCandidate={slash.handleSelectCandidate}
              onSend={stream.executeSend}
            />
          </>
        )}
      </div>

      <CodingModals
        isSessionSettingsOpen={detail.isSessionSettingsOpen}
        onCloseSessionSettings={() => detail.setIsSessionSettingsOpen(false)}
        sessionDetail={detail.sessionDetail}
        sessionSelectedTools={detail.sessionSelectedTools}
        setSessionSelectedTools={detail.setSessionSelectedTools}
        sessionTitleDraft={detail.sessionTitleDraft}
        setSessionTitleDraft={detail.setSessionTitleDraft}
        savingSessionTools={detail.savingSessionTools}
        onSaveSessionTools={detail.handleSaveSessionTools}
        onResetSessionTools={detail.handleResetSessionTools}
        isUserDefaultsOpen={detail.isUserDefaultsOpen}
        onCloseUserDefaults={() => detail.setIsUserDefaultsOpen(false)}
        loadingUserDefaults={detail.loadingUserDefaults}
        userDefaults={detail.userDefaults}
        userDefaultsSelectedTools={detail.userDefaultsSelectedTools}
        setUserDefaultsSelectedTools={detail.setUserDefaultsSelectedTools}
        savingUserDefaults={detail.savingUserDefaults}
        onSaveUserDefaults={detail.handleSaveUserDefaults}
        isNewSessionModalOpen={sessions.isNewSessionModalOpen}
        onCloseNewSession={() => sessions.setIsNewSessionModalOpen(false)}
        newSessionTitle={sessions.newSessionTitle}
        setNewSessionTitle={sessions.setNewSessionTitle}
        newSessionBackend={sessions.newSessionBackend}
        setNewSessionBackend={sessions.setNewSessionBackend}
        backendManuallySelected={sessions.backendManuallySelected}
        creatingSession={sessions.creatingSession}
        selectedProjectItem={selectedProjectItem}
        onCreateSession={sessions.handleCreateSession}
      />
    </div>
  );
}
