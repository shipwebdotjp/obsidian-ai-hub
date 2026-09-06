import type { RefObject } from "react";
import { ChevronRight, Settings } from "lucide-react";
import type { Agent } from "../../api/types";

interface AgentWorkspaceHeaderProps {
  activeAgent: Agent;
  leftPaneCollapsed: boolean;
  onExpandPane: () => void;
  mobileDrawerTriggerRef: RefObject<HTMLButtonElement>;
  onOpenDrawer: () => void;
  onOpenEditForm: (agent: Agent) => void;
}

/** 作業中エージェントのヘッダー（名称・プロンプト・設定編集）。 */
export function AgentWorkspaceHeader({
  activeAgent,
  leftPaneCollapsed,
  onExpandPane,
  mobileDrawerTriggerRef,
  onOpenDrawer,
  onOpenEditForm,
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
