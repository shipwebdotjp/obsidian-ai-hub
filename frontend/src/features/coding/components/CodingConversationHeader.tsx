import type { RefObject } from "react";
import { ChevronRight } from "lucide-react";
import type {
  CodingRun,
  CodingSession,
  CodingSessionDetail,
  GitStatus,
} from "../../../api/coding";

interface CodingConversationHeaderProps {
  selectedSession: CodingSession;
  sessionDetail: CodingSessionDetail | null;
  gitStatus: GitStatus | null;
  currentRun: CodingRun | null;
  leftPaneCollapsed: boolean;
  onExpandLeftPane: () => void;
  drawerTriggerBtnRef: RefObject<HTMLButtonElement>;
  onOpenMobileDrawer: () => void;
  onOpenSessionSettings: () => void;
  onCancelRun: () => void;
}

/** 会話ヘッダー（タイトル・git 状態・操作）と dirty tree 警告バナー。 */
export function CodingConversationHeader({
  selectedSession,
  sessionDetail,
  gitStatus,
  currentRun,
  leftPaneCollapsed,
  onExpandLeftPane,
  drawerTriggerBtnRef,
  onOpenMobileDrawer,
  onOpenSessionSettings,
  onCancelRun,
}: CodingConversationHeaderProps) {
  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
        <div className="min-w-0 flex-1 mr-2">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              ref={drawerTriggerBtnRef}
              type="button"
              onClick={onOpenMobileDrawer}
              className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden shrink-0"
              aria-label="プロジェクト / セッションを選択"
            >
              プロジェクト / セッション
            </button>
            {leftPaneCollapsed && (
              <button
                type="button"
                onClick={onExpandLeftPane}
                className="hidden h-8 w-8 items-center justify-center rounded border border-slate-300 bg-slate-900 text-white hover:bg-slate-800 cursor-pointer lg:inline-flex shrink-0"
                aria-label="サイドバーを展開"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            )}
            <h1 className="text-sm font-semibold text-slate-800 truncate">{selectedSession.title}</h1>
            {sessionDetail?.has_custom_tools ? (
              <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                会話固有ツール設定
              </span>
            ) : (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                既定ツール適用
              </span>
            )}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span className="rounded bg-slate-100 px-1.5 py-0.5 font-medium uppercase text-slate-700">
              {selectedSession.backend}
            </span>
            <span>{selectedSession.repo_path}</span>
            {gitStatus && (
              <div className="flex items-center gap-1.5 border-l border-slate-200 pl-2">
                <span className="font-mono font-medium text-slate-700">
                  {gitStatus.branch || "detached"}
                </span>
                <span className="font-mono text-slate-600" title="ahead / behind">
                  ↑{gitStatus.ahead} ↓{gitStatus.behind}
                </span>
                <span className="font-mono text-emerald-600 font-medium">
                  +{gitStatus.insertions}
                </span>
                <span className="font-mono text-rose-600 font-medium">
                  -{gitStatus.deletions}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenSessionSettings}
            disabled={!sessionDetail}
            className="rounded border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            会話設定 ⚙
          </button>
          {currentRun && currentRun.status === "running" && (
            <button
              type="button"
              onClick={onCancelRun}
              className="rounded bg-rose-600 px-3 py-1 text-xs font-medium text-white hover:bg-rose-700 cursor-pointer"
            >
              キャンセル
            </button>
          )}
        </div>
      </div>

      {/* Dirty tree warning banner if run started with uncommitted changes */}
      {currentRun?.dirty_tree_at_start && (
        <details className="bg-amber-50 text-xs text-amber-800 border-b border-amber-200">
          <summary className="cursor-pointer px-4 py-2 font-semibold hover:bg-amber-100/60 flex items-center justify-between">
            <span>⚠️ 開始時に未コミットの変更があります</span>
            <span className="text-[10px] text-amber-700 font-normal">クリックで展開/折りたたみ</span>
          </summary>
          <div className="px-4 pb-2">
            <pre className="mt-1 max-h-32 overflow-y-auto text-[10px] font-mono bg-amber-100/50 p-1.5 rounded">
              {currentRun.dirty_tree_at_start}
            </pre>
          </div>
        </details>
      )}
    </>
  );
}
