import type { RefObject } from "react";
import { ChevronLeft } from "lucide-react";
import type { CodingProjectItem, CodingSession } from "../../../api/coding";
import { formatYmdWithDow } from "../../../utils/date";

interface CodingSidebarProps {
  mobileDrawerOpen: boolean;
  onCloseMobileDrawer: () => void;
  drawerCloseBtnRef: RefObject<HTMLButtonElement>;
  mobileDrawerRef: RefObject<HTMLDivElement>;
  leftPaneCollapsed: boolean;
  onCollapseLeftPane: () => void;
  loadingProjects: boolean;
  validProjects: CodingProjectItem[];
  selectedProjectId: number | null;
  onSelectProject: (projectId: number) => void;
  loadingSessions: boolean;
  sessions: CodingSession[];
  selectedSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  selectedProjectItem: CodingProjectItem | undefined;
  onOpenNewSession: () => void;
  onOpenUserDefaults: () => void;
  onDeleteSession: (sessionId: string, e: React.MouseEvent) => void;
}

/** モバイルドロワーとデスクトップ左ペイン（プロジェクト/セッション一覧）。 */
export function CodingSidebar({
  mobileDrawerOpen,
  onCloseMobileDrawer,
  drawerCloseBtnRef,
  mobileDrawerRef,
  leftPaneCollapsed,
  onCollapseLeftPane,
  loadingProjects,
  validProjects,
  selectedProjectId,
  onSelectProject,
  loadingSessions,
  sessions,
  selectedSessionId,
  onSelectSession,
  selectedProjectItem,
  onOpenNewSession,
  onOpenUserDefaults,
  onDeleteSession,
}: CodingSidebarProps) {
  return (
    <>
      {/* Mobile Drawer Overlay */}
      {mobileDrawerOpen && (
        <div
          ref={mobileDrawerRef}
          className="fixed inset-0 z-50 flex lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="プロジェクトとセッションの選択"
        >
          <div className="flex h-full w-80 max-w-[85vw] flex-col border-r border-slate-200 bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50">
              <h2 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                プロジェクト & セッション
              </h2>
              <button
                ref={drawerCloseBtnRef}
                type="button"
                onClick={onCloseMobileDrawer}
                className="rounded p-1 text-slate-500 hover:bg-slate-200 cursor-pointer"
                aria-label="サイドバーを閉じる"
              >
                ✕
              </button>
            </div>

            <div className="flex-1 overflow-y-auto divide-y divide-slate-200">
              {/* Mobile Project Selector Section */}
              <div className="p-3">
                <div className="mb-2 text-[11px] font-semibold text-slate-500 uppercase">
                  プロジェクト選択
                </div>
                {loadingProjects ? (
                  <div className="p-2 text-xs text-slate-500">読み込み中...</div>
                ) : validProjects.length === 0 ? (
                  <div className="p-2 text-xs text-slate-500">プロジェクトがありません</div>
                ) : (
                  <div className="space-y-1">
                    {validProjects.map((item) => {
                      const isSelected = item.project.project_id === selectedProjectId;
                      return (
                        <button
                          key={item.project.project_id}
                          type="button"
                          onClick={() => {
                            onSelectProject(item.project.project_id);
                          }}
                          className={`w-full rounded px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                            isSelected
                              ? "bg-slate-900 font-medium text-white"
                              : "text-slate-700 hover:bg-slate-100"
                          }`}
                        >
                          <span className="truncate">{item.project.display_name}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Mobile Sessions Section */}
              <div className="p-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-[11px] font-semibold text-slate-500 uppercase">
                    セッション一覧
                  </span>
                  {selectedProjectItem && (
                    <button
                      type="button"
                      onClick={() => {
                        onOpenNewSession();
                        onCloseMobileDrawer();
                      }}
                      className="rounded bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-slate-800 cursor-pointer"
                    >
                      + 新規
                    </button>
                  )}
                </div>

                {loadingSessions ? (
                  <div className="p-2 text-xs text-slate-500">セッション読み込み中...</div>
                ) : sessions.length === 0 ? (
                  <div className="p-2 text-xs text-slate-500">セッションがありません</div>
                ) : (
                  <div className="space-y-1">
                    {sessions.map((sess) => {
                      const isSelected = sess.session_id === selectedSessionId;
                      return (
                        <button
                          key={sess.session_id}
                          type="button"
                          data-testid="memory-row"
                          data-selected={isSelected}
                          onClick={() => {
                            onSelectSession(sess.session_id);
                            onCloseMobileDrawer();
                          }}
                          className={`w-full flex cursor-pointer items-center justify-between rounded px-2.5 py-2 text-left text-xs transition-colors ${
                            isSelected
                              ? "bg-slate-200 border-l-4 border-slate-800 font-medium text-slate-900"
                              : "text-slate-700 hover:bg-slate-50"
                          }`}
                        >
                          <div className="min-w-0 flex-1 truncate">{sess.title}</div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
          <button
            type="button"
            aria-label="オーバーレイを閉じる"
            onClick={onCloseMobileDrawer}
            className="flex-1 bg-slate-900/40 cursor-pointer"
          />
        </div>
      )}

      {/* Desktop Collapsible Left Pane */}
      {!leftPaneCollapsed && (
      <div className="hidden h-full w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="flex items-center justify-end border-b border-slate-200 p-2">
          <button
            type="button"
            onClick={onCollapseLeftPane}
            className="rounded p-1 text-slate-500 hover:bg-slate-100 cursor-pointer"
            aria-label="サイドバーを畳む"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        </div>

        {/* Upper Section: Project List */}
        <div className="flex flex-1 flex-col min-h-0 border-b border-slate-200">
          <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
            <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">プロジェクト</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {loadingProjects ? (
              <div className="p-3 text-xs text-slate-500">読み込み中...</div>
            ) : validProjects.length === 0 ? (
              <div className="p-3 text-xs text-slate-500">プロジェクトがありません</div>
            ) : (
              validProjects.map((item) => {
                const isSelected = item.project.project_id === selectedProjectId;
                return (
                  <button
                    key={item.project.project_id}
                    type="button"
                    onClick={() => onSelectProject(item.project.project_id)}
                    className={`w-full rounded px-3 py-2 text-left text-xs transition-colors cursor-pointer ${
                      isSelected
                        ? "bg-slate-900 font-medium text-white"
                        : "text-slate-700 hover:bg-slate-100"
                    }`}
                  >
                    <span className="truncate">{item.project.display_name}</span>
                    {item.project.domain && (
                      <div className={`mt-0.5 text-[10px] ${isSelected ? "text-slate-300" : "text-slate-400"}`}>
                        {item.project.domain} • {item.project.status}
                      </div>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* Lower Section: Session List */}
        <div className="flex flex-1 flex-col min-h-0">
          <div className="flex items-center justify-between border-b border-slate-200 p-3 bg-slate-50/50">
            <h2 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">セッション</h2>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={onOpenUserDefaults}
                className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                title="ユーザー既定の利用可能ツール設定"
              >
                既定設定
              </button>
              {selectedProjectItem && (
                <button
                  type="button"
                  onClick={onOpenNewSession}
                  className="rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white hover:bg-blue-700 cursor-pointer"
                  title="新規セッション作成"
                >
                  + 新規
                </button>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {loadingSessions ? (
              <div className="p-3 text-xs text-slate-500">セッション読み込み中...</div>
            ) : sessions.length === 0 ? (
              <div className="p-3 text-xs text-slate-500">
                セッションがありません。「+ 新規」から作成してください。
              </div>
            ) : (
              sessions.map((sess) => {
                const isSelected = sess.session_id === selectedSessionId;
                const dateStr = sess.created_at ? formatYmdWithDow(sess.created_at.slice(0, 10)) : "";
                return (
                  <div
                    key={sess.session_id}
                    data-testid="memory-row"
                    data-selected={isSelected}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSelectSession(sess.session_id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onSelectSession(sess.session_id);
                      }
                    }}
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
                      onClick={(e) => onDeleteSession(sess.session_id, e)}
                      className="ml-2 hidden rounded p-1 text-slate-400 hover:bg-slate-300 hover:text-slate-700 group-hover:block cursor-pointer"
                      title="削除"
                    >
                      ✕
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
      )}
    </>
  );
}
