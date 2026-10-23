import type { RefObject } from "react";
import { Check, ChevronRight, Link2, Settings, TimerOff } from "lucide-react";
import type { Agent } from "../../api/types";

interface AgentWorkspaceHeaderProps {
  activeAgent: Agent;
  leftPaneCollapsed: boolean;
  onExpandPane: () => void;
  mobileDrawerTriggerRef: RefObject<HTMLButtonElement>;
  onOpenDrawer: () => void;
  onOpenEditForm: (agent: Agent) => void;
  onCopyShortcutUrl: (agentId: string) => void;
  shortcutUrlCopied: boolean;
  isEphemeralSession: boolean;
  onEndEphemeralSession: () => void;
}

/** 作業中エージェントのヘッダー（名称・プロンプト・設定編集）。 */
export function AgentWorkspaceHeader({
  activeAgent,
  leftPaneCollapsed,
  onExpandPane,
  mobileDrawerTriggerRef,
  onOpenDrawer,
  onOpenEditForm,
  onCopyShortcutUrl,
  shortcutUrlCopied,
  isEphemeralSession,
  onEndEphemeralSession,
}: AgentWorkspaceHeaderProps) {
  return (
    <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
      <div className="flex items-center gap-2 min-w-0">
        <button
          ref={mobileDrawerTriggerRef}
          type="button"
          onClick={onOpenDrawer}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer lg:hidden"
          aria-label="エージェントと会話を選択"
        >
          エージェント / 会話
        </button>
        {leftPaneCollapsed && (
          <button
            type="button"
            onClick={onExpandPane}
            className="hidden h-8 w-8 items-center justify-center rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 cursor-pointer lg:inline-flex"
            aria-label="サイドバーを展開"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        )}
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            {activeAgent.name}
            {isEphemeralSession && (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2 py-0.5 text-[11px] font-medium text-violet-800"
                title="履歴・実行記録を残さない一時的な会話です"
              >
                <TimerOff className="h-3 w-3" />
                一時会話
              </span>
            )}
          </h3>
          <p className="text-[11px] text-slate-500 truncate max-w-lg">
            {activeAgent.system_prompt}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        {isEphemeralSession ? (
          <button
            type="button"
            onClick={onEndEphemeralSession}
            className="inline-flex h-8 items-center gap-1 rounded border border-violet-300 bg-violet-700 px-2 text-xs text-white hover:bg-violet-800 cursor-pointer"
            aria-label="一時会話を終了して削除"
            title="この一時会話を終了し、履歴・実行記録を削除します"
          >
            <TimerOff className="h-4 w-4" />
            <span>終了して削除</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={() => onCopyShortcutUrl(activeAgent.agent_id)}
            className="inline-flex h-8 items-center gap-1 rounded border border-slate-300 bg-white px-2 text-xs text-slate-700 hover:bg-slate-50 cursor-pointer"
            aria-label="新しい会話URLをコピー"
          >
            {shortcutUrlCopied ? <Check className="h-4 w-4 text-emerald-600" /> : <Link2 className="h-4 w-4" />}
            <span>{shortcutUrlCopied ? "コピー済み" : "URL"}</span>
          </button>
        )}
        <button
          type="button"
          onClick={() => onOpenEditForm(activeAgent)}
          className="inline-flex h-8 w-8 items-center justify-center rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 cursor-pointer"
          aria-label="設定編集"
        >
          <Settings className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
