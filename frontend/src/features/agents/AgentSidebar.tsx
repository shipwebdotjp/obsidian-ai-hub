import React, { type ReactNode, type RefObject } from "react";
import { ChevronLeft, MoreVertical, Pencil, Pin, Trash2, X } from "lucide-react";
import type {
  Agent,
  AgentMessageSearchResult,
  AgentSession,
} from "../../api/types";

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

interface AgentSidebarProps {
  agents: Agent[];
  selectedAgentId: string | null;
  isCreatingAgent: boolean;
  isEditingAgent: boolean;
  actionError: string | null;
  onOpenCreateForm: () => void;
  onSelectAgentRow: (agentId: string) => void;
  onToggleAgentPin: (agent: Agent, e: React.MouseEvent) => void;
  sessions: AgentSession[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onCreateSession: () => void;
  sessionSearchQuery: string;
  onSessionSearchQueryChange: (query: string) => void;
  sessionSearchResults: AgentMessageSearchResult[];
  isSessionSearchLoading: boolean;
  sessionSearchError: string | null;
  onSelectSearchResult: (result: AgentMessageSearchResult) => void;
  activeSessionMenuId: string | null;
  onToggleSessionMenu: (sessionId: string) => void;
  onToggleSessionPin: (session: AgentSession, e: React.MouseEvent) => void;
  onOpenEditTitle: (session: AgentSession) => void;
  onDeleteSessionTarget: (session: AgentSession) => void;
  leftPaneOpen: boolean;
  onCloseDrawer: () => void;
  mobileDrawerCloseRef: RefObject<HTMLButtonElement>;
  mobileDrawerRef: RefObject<HTMLDivElement>;
  leftPaneCollapsed: boolean;
  onCollapsePane: () => void;
}

/** モバイルドロワーとデスクトップ左ペイン（エージェント/会話履歴一覧・検索）。 */
export function AgentSidebar({
  agents,
  selectedAgentId,
  isCreatingAgent,
  isEditingAgent,
  actionError,
  onOpenCreateForm,
  onSelectAgentRow,
  onToggleAgentPin,
  sessions,
  selectedSessionId,
  onSelectSession,
  onCreateSession,
  sessionSearchQuery,
  onSessionSearchQueryChange,
  sessionSearchResults,
  isSessionSearchLoading,
  sessionSearchError,
  onSelectSearchResult,
  activeSessionMenuId,
  onToggleSessionMenu,
  onToggleSessionPin,
  onOpenEditTitle,
  onDeleteSessionTarget,
  leftPaneOpen,
  onCloseDrawer,
  mobileDrawerCloseRef,
  mobileDrawerRef,
  leftPaneCollapsed,
  onCollapsePane,
}: AgentSidebarProps) {
  const sidebarContent = (
    <>

        {/* Upper Section: AI Agent List */}
        <div className="flex flex-1 flex-col min-h-0 border-b border-slate-200">
          <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
            <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">AIエージェント</h2>
            <button
              type="button"
              onClick={onOpenCreateForm}
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
                    onClick={() => onSelectAgentRow(agent.agent_id)}
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
                    onToggle={(e) => onToggleAgentPin(agent, e)}
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
                onClick={onCreateSession}
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
              onChange={(e) => onSessionSearchQueryChange(e.target.value)}
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
                    onClick={() => onSelectSearchResult(result)}
                    data-testid={`agent-message-search-result-${result.message_id}`}
                    className="block w-full rounded px-3 py-2 text-left text-xs text-slate-700 transition hover:bg-slate-100 cursor-pointer"
                  >
                    <div className="flex items-center gap-1 truncate text-[10px] text-slate-500">
                      <span className="font-semibold text-slate-700">{result.agent_name}</span>
                      <span aria-hidden="true">/</span>
                      <span className="truncate">{result.session_title}</span>
                    </div>
                    <div className="mt-0.5 max-h-8 overflow-hidden break-words text-slate-800 leading-4">
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
                  data-testid="memory-row"
                  data-selected={selectedSessionId === s.session_id ? "true" : "false"}
                  onClick={(e) => {
                    // 行内の操作メニューからのクリックでは選択処理を行わない。
                    if ((e.target as HTMLElement).closest("[data-session-menu]")) {
                      return;
                    }
                    onSelectSession(s.session_id);
                  }}
                  className={`group relative flex items-center justify-between rounded-lg px-3 py-2 text-xs transition cursor-pointer ${
                    selectedSessionId === s.session_id
                      ? "bg-slate-200 border-l-4 border-slate-800 text-slate-900 font-medium"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectSession(s.session_id);
                    }}
                    aria-label={`会話「${s.title}」を開く`}
                    className="truncate text-left cursor-pointer flex-1 min-w-0 mr-1 flex items-center gap-1.5 rounded focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-slate-500"
                  >
                    {s.pinned_at && (
                      <Pin className="h-3 w-3 shrink-0 fill-amber-400 text-amber-500" />
                    )}
                    <span className="truncate font-medium">{s.title}</span>
                  </button>
                  <div className="relative shrink-0" data-session-menu>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onToggleSessionMenu(s.session_id);
                      }}
                      className={`inline-flex h-6 w-6 items-center justify-center rounded cursor-pointer transition ${
                        selectedSessionId === s.session_id
                          ? "text-slate-700 hover:text-slate-900 hover:bg-slate-300"
                          : "text-slate-400 hover:text-slate-700 hover:bg-slate-200"
                      }`}
                      aria-label="操作メニュー"
                      aria-expanded={activeSessionMenuId === s.session_id}
                    >
                      <MoreVertical className="h-3.5 w-3.5" />
                    </button>
                    {activeSessionMenuId === s.session_id && (
                      <div className="absolute right-0 top-full mt-1 z-30 w-36 rounded-lg border border-slate-200 bg-white p-1 shadow-lg text-xs space-y-1">
                        <button
                          type="button"
                          onClick={(e) => {
                            onToggleSessionPin(s, e);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-1.5 bg-slate-900 text-white hover:bg-slate-800 rounded text-left cursor-pointer"
                          aria-label={s.pinned_at ? "会話のピン留めを解除" : "会話をピン留めする"}
                        >
                          <Pin className={`h-3.5 w-3.5 ${s.pinned_at ? "fill-amber-400 text-amber-300" : "text-white"}`} />
                          {s.pinned_at ? "ピン留め解除" : "ピン留め"}
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenEditTitle(s);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-1.5 bg-slate-900 text-white hover:bg-slate-800 rounded text-left cursor-pointer"
                          aria-label="会話タイトルを変更"
                        >
                          <Pencil className="h-3.5 w-3.5 text-white" />
                          タイトル変更
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSessionTarget(s);
                          }}
                          className="flex w-full items-center gap-2 px-3 py-1.5 bg-rose-800 text-white hover:bg-rose-900 rounded text-left cursor-pointer"
                          aria-label="会話を削除"
                        >
                          <Trash2 className="h-3.5 w-3.5 text-white" />
                          削除
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
    </>
  );

  return (
    <>
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
                onClick={onCloseDrawer}
              >
                <X className="h-4 w-4" />
              </SidebarIconButton>
            </div>
            {sidebarContent}
          </div>
          <button
            type="button"
            aria-label="オーバーレイを閉じる"
            onClick={onCloseDrawer}
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
              onClick={onCollapsePane}
            >
              <ChevronLeft className="h-4 w-4" />
            </SidebarIconButton>
          </div>
          {sidebarContent}
        </div>
      )}
    </>
  );
}
